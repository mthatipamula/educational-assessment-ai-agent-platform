"""Scoring agent: scores a student's response against the item's rubric, with evidence and a confidence value.

Responsible-AI rules:
- The student's text is screened first and wrapped as data; manipulation attempts are flagged, not obeyed.
- Every criterion's points are clamped to the rubric, and the total is computed in code, not by the model.
- Low confidence, safety flags or a refusal send the response to a human scorer; the AI score is only advisory.
"""
from __future__ import annotations

import json
import logging

from .. import config, db, llm, safety, telemetry
from . import sandbox

log = logging.getLogger(__name__)

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "points_awarded": {"type": "number"},
                    "evidence": {"type": "string", "description": "Exact quote from the response, or 'none'"},
                    "reasoning": {"type": "string"},
                },
                "required": ["criterion", "points_awarded", "evidence", "reasoning"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "number", "description": "0 to 1: how sure you are the scores match the rubric"},
        "feedback_for_student": {"type": "string"},
        "misconception": {"type": "string", "description": "Main misconception shown, or empty"},
    },
    "required": ["criteria", "confidence", "feedback_for_student", "misconception"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are an experienced, fair scorer of K-12 assessments. Score strictly by the rubric: award points only "
    "for what the response shows, quote the evidence, and do not reward length or penalize spelling unless the "
    "rubric says so. Give confidence below 0.7 when the response is ambiguous, partly off-topic, or the rubric "
    "doesn't clearly decide it. Feedback for the student: 2-3 encouraging, specific sentences that point to the "
    "next step without giving away the full answer. " + safety.SAFE_DATA_NOTE
)


async def score_response(response_id: str) -> dict:
    try:
        return await _score(response_id)
    except Exception as err:  # noqa: BLE001 - never leave a response stuck: send it to a teacher
        log.exception("Scoring failed for %s", response_id)
        await db.pool.execute(
            """UPDATE responses SET status = 'NEEDS_REVIEW', needs_human_review = TRUE, review_reasons = $2
               WHERE id = $1 AND status = 'SCORING'""", response_id, [f"Automatic scoring failed: {type(err).__name__}"])
        return {"status": "NEEDS_REVIEW", "error": str(err)}


async def _score(response_id: str) -> dict:
    r = await db.pool.fetchrow(
        """SELECT r.id, r.student_id, r.response_text, i.* FROM responses r JOIN items i ON i.id = r.item_id
           WHERE r.id = $1""", response_id)
    item = dict(r)
    rubric = item["rubric"]
    max_score = sum(c["max_points"] for c in rubric)
    reasons: list[str] = []

    if item["item_type"] == "MULTIPLE_CHOICE":
        chosen = r["response_text"].strip().upper()[:1]
        correct = chosen == item["answer_key"].strip().upper()
        result = {"criteria": [{"criterion": "Correct choice", "points_awarded": 1 if correct else 0, "evidence": chosen,
                                "reasoning": "Matches the answer key." if correct else "Does not match the answer key."}],
                  "confidence": 1.0, "method": "answer key",
                  "feedback_for_student": "Correct!" if correct else "Not quite. Try working out the unit price first."}
        total, conf = (1.0 if correct else 0.0), 1.0
        safety_result = {"flags": []}
    elif item["item_type"] == "CODE":
        run = await sandbox.run_tests(r["response_text"], item["tests"] or [])
        passed = sum(1 for t in run["results"] if t["passed"])
        total, conf = float(passed), 1.0
        result = {"criteria": [{"criterion": "Passes test cases", "points_awarded": passed, "evidence": f"{passed}/{len(run['results'])} tests passed",
                                "reasoning": run.get("error") or "Deterministic test run in the sandbox."}],
                  "confidence": 1.0, "method": "sandbox tests", "tests": run["results"],
                  "feedback_for_student": "All tests pass. Nice work!" if passed == len(run["results"])
                  else "Some tests fail. Check the empty-list case and the rounding."}
        safety_result = {"flags": []}
    else:
        screened = await safety.screen_student_text(r["response_text"], "SCORING", r["student_id"])
        safety_result = screened.as_dict()
        rubric_text = "\n".join(f"- {c['criterion']} (max {c['max_points']}): {c['descriptors']}" for c in rubric)
        session = llm.ModelSession("scoring")
        try:
            out = await session.json(
                SCORE_SCHEMA, system=SYSTEM, max_tokens=8000,
                messages=[{"role": "user", "content": (
                    f"Item (standard {item['standard_code']}):\n{item['stem']}\n\nRubric:\n{rubric_text}\n\n"
                    f"Exemplar answer (for the scorer only):\n{item['answer_key']}\n\n"
                    f"<student_response>\n{screened.text}\n</student_response>")}])
        except (llm.NoProviderAvailable, llm.ModelRefusal) as err:
            await db.pool.execute(
                """UPDATE responses SET status = 'NEEDS_REVIEW', needs_human_review = TRUE, max_score = $2,
                   review_reasons = $3, safety = $4 WHERE id = $1""",
                response_id, max_score, [f"AI scoring unavailable: {err}"], safety_result)
            return {"status": "NEEDS_REVIEW", "error": str(err)}

        # Never trust model arithmetic: clamp each criterion to its maximum and add up in code.
        by_name = {c["criterion"].lower(): c for c in rubric}
        total = 0.0
        for c in out["criteria"]:
            limit = by_name.get(c["criterion"].lower(), {}).get("max_points", 0)
            c["points_awarded"] = max(0.0, min(float(c["points_awarded"]), float(limit)))
            c["max_points"] = limit
            total += c["points_awarded"]
        conf = max(0.0, min(1.0, float(out["confidence"])))
        result = {**out, "confidence": conf, "method": "rubric scoring", "served_by": session.served_by}
        if conf < config.SCORING_REVIEW_CONFIDENCE:
            reasons.append(f"Low confidence ({conf:.2f})")
        if "PROMPT_INJECTION" in screened.flags:
            reasons.append("Response contains instructions aimed at the scorer")
        if screened.escalate:
            reasons.append("Possible student wellbeing concern: notify counselor")
        if "CLASSIFIER_UNAVAILABLE" in screened.flags:
            reasons.append("Safety classifier unavailable")

        if out["misconception"]:
            await _share_with_tutor(r["student_id"], str(item["id"]), out["misconception"], total, max_score)

    needs_review = bool(reasons)
    await db.pool.execute(
        """UPDATE responses SET ai_score = $2, max_score = $3, ai_confidence = $4, ai_result = $5, safety = $6,
               needs_human_review = $7, review_reasons = $8, status = $9 WHERE id = $1""",
        response_id, total, max_score, conf, result, safety_result, needs_review, reasons,
        "NEEDS_REVIEW" if needs_review else "SCORED")
    log.info('{"event":"scored","trace":"%s","response":"%s","score":%s,"review":%s}',
             telemetry.trace_id_var.get(), response_id, total, json.dumps(needs_review))
    return {"status": "NEEDS_REVIEW" if needs_review else "SCORED", "score": total, "max": max_score}


async def _share_with_tutor(student_id: str, item_id: str, misconception: str, score: float, max_score: float) -> None:
    """Shared state: the scoring agent leaves what it learned where the tutor agent will read it."""
    await db.pool.execute(
        """INSERT INTO learning_sessions (student_id, item_id, state) VALUES ($1, $2::uuid,
               jsonb_build_object('hint_level', 0, 'attempts', 1, 'misconceptions', jsonb_build_array($3::text),
                                  'last_score', $4::numeric, 'max_score', $5::numeric))
           ON CONFLICT (student_id, item_id) DO UPDATE SET
               state = learning_sessions.state
                       || jsonb_build_object('last_score', $4::numeric, 'max_score', $5::numeric,
                                             'attempts', COALESCE((learning_sessions.state->>'attempts')::int, 0) + 1)
                       || jsonb_build_object('misconceptions',
                              COALESCE(learning_sessions.state->'misconceptions', '[]'::jsonb) || to_jsonb($3::text)),
               updated_at = now()""",
        student_id, item_id, misconception, score, max_score)
