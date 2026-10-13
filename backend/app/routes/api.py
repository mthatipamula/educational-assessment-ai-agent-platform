from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, embeddings, evals, llm, rag, safety, telemetry
from ..agents import authoring, sandbox, scoring, tutor
from ..auth import User, current_user, require_teacher

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)
_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """Background work keeps the request's trace ID (contextvars are copied into the task)."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    task.add_done_callback(lambda t: t.cancelled() or not t.exception() or log.error("Background task failed: %r", t.exception()))


def _student_view(item: dict) -> dict:
    """Students never receive the answer key or the authoring notes."""
    return {k: v for k, v in item.items() if k not in ("answer_key", "review_notes", "embedding", "embed_model")}


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "role": user.role}


@router.get("/status")
async def status(user: User = Depends(current_user)):
    counts = await db.pool.fetchrow(
        """SELECT (SELECT count(*) FROM knowledge_chunks) AS chunks,
                  (SELECT count(*) FROM knowledge_chunks WHERE embedding IS NOT NULL) AS embedded,
                  (SELECT string_agg(DISTINCT embed_model, ', ') FROM knowledge_chunks) AS embed_models""")
    return {"llm": llm.status(), "embeddings": embeddings.status(), "knowledgeBase": dict(counts)}


@router.get("/standards")
async def standards(user: User = Depends(current_user)):
    return [dict(r) for r in await db.pool.fetch("SELECT * FROM standards ORDER BY subject, grade, code")]


@router.get("/items")
async def items(status: str | None = None, user: User = Depends(current_user)):
    if user.role == "STUDENT":
        status = "APPROVED"
    rows = await db.pool.fetch(
        """SELECT i.id, i.standard_code, s.title AS standard_title, i.item_type, i.difficulty, i.stem, i.choices,
                  i.answer_key, i.rubric, i.tests, i.status, i.source, i.review_notes, i.created_at, i.decided_by
           FROM items i JOIN standards s ON s.code = i.standard_code
           WHERE ($1::text IS NULL OR i.status = $1) AND i.decided_by IS DISTINCT FROM 'eval'
           ORDER BY i.created_at DESC""", status)
    out = [dict(r) for r in rows]
    return [_student_view(i) for i in out] if user.role == "STUDENT" else out


class Decision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    note: str = Field(default="", max_length=1000)


@router.post("/items/{item_id}/decision")
async def decide(item_id: uuid.UUID, body: Decision, user: User = Depends(current_user)):
    require_teacher(user)
    status = "APPROVED" if body.decision == "APPROVE" else "REJECTED"
    done = await db.pool.execute(
        """UPDATE items SET status = $2, decided_by = $3, decided_at = now(),
               review_notes = COALESCE(review_notes, '{}'::jsonb) || jsonb_build_object('teacher_note', $4::text)
           WHERE id = $1 AND status = 'DRAFT'""", item_id, status, user.name, body.note)
    if done.endswith("0"):
        raise HTTPException(409, "Only draft items can be approved or rejected")
    return {"id": str(item_id), "status": status}


class AuthoringRequest(BaseModel):
    standard_code: str
    item_type: Literal["MULTIPLE_CHOICE", "CONSTRUCTED_RESPONSE", "CODE"]
    difficulty: Literal["EASY", "MEDIUM", "HARD"]
    topic: str = Field(default="", max_length=200)


@router.post("/authoring/runs", status_code=202)
async def start_authoring(body: AuthoringRequest, user: User = Depends(current_user)):
    require_teacher(user)
    if not await db.pool.fetchval("SELECT 1 FROM standards WHERE code = $1", body.standard_code):
        raise HTTPException(422, "Unknown standard")
    request = body.model_dump(exclude_none=True)
    run_id = await db.pool.fetchval(
        "INSERT INTO agent_runs (agent, input, trace_id) VALUES ('authoring', $1, $2) RETURNING id",
        request, telemetry.trace_id_var.get())
    _spawn(authoring.run(run_id, request))
    return {"runId": str(run_id)}


@router.get("/authoring/runs")
async def authoring_runs(user: User = Depends(current_user)):
    require_teacher(user)
    return [dict(r) for r in await db.pool.fetch(
        "SELECT * FROM agent_runs WHERE agent = 'authoring' AND input->>'eval' IS NULL ORDER BY started_at DESC LIMIT 20")]


@router.get("/authoring/runs/{run_id}")
async def authoring_run(run_id: uuid.UUID, user: User = Depends(current_user)):
    require_teacher(user)
    r = await db.pool.fetchrow("SELECT * FROM agent_runs WHERE id = $1", run_id)
    if r is None:
        raise HTTPException(404, "Run not found")
    return dict(r)


class ResponseIn(BaseModel):
    item_id: uuid.UUID
    response_text: str = Field(min_length=1, max_length=20000)


@router.post("/responses", status_code=202)
async def submit_response(body: ResponseIn, user: User = Depends(current_user)):
    if user.role != "STUDENT":
        raise HTTPException(403, "Students submit responses")
    item = await db.pool.fetchrow("SELECT item_type FROM items WHERE id = $1 AND status = 'APPROVED'", body.item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    text = body.response_text if item["item_type"] == "CODE" else safety.redact_pii(body.response_text)[0]
    rid = await db.pool.fetchval(
        "INSERT INTO responses (student_id, item_id, response_text) VALUES ($1, $2, $3) RETURNING id",
        user.id, body.item_id, text)
    _spawn(scoring.score_response(rid))
    return {"id": str(rid), "status": "SCORING"}


@router.get("/responses")
async def list_responses(user: User = Depends(current_user)):
    rows = await db.pool.fetch(
        """SELECT r.id, r.student_id, st.name AS student_name, r.item_id, i.stem, i.item_type, r.response_text,
                  r.ai_score, r.max_score, r.ai_confidence, r.ai_result, r.safety, r.needs_human_review,
                  r.review_reasons, r.human_score, r.human_note, r.reviewed_by, r.status, r.created_at
           FROM responses r JOIN items i ON i.id = r.item_id JOIN students st ON st.id = r.student_id
           WHERE ($1::text IS NULL OR r.student_id = $1) AND r.student_id <> 'STU-EVAL'
           ORDER BY r.created_at DESC LIMIT 200""", user.id if user.role == "STUDENT" else None)
    return [dict(r) for r in rows]


class Review(BaseModel):
    score: float = Field(ge=0)
    note: str = Field(default="", max_length=1000)


@router.post("/responses/{response_id}/review")
async def review_response(response_id: uuid.UUID, body: Review, user: User = Depends(current_user)):
    require_teacher(user)
    r = await db.pool.fetchrow("SELECT max_score FROM responses WHERE id = $1", response_id)
    if r is None:
        raise HTTPException(404, "Response not found")
    if r["max_score"] is not None and body.score > float(r["max_score"]):
        raise HTTPException(422, f"Score cannot exceed {r['max_score']}")
    await db.pool.execute(
        """UPDATE responses SET human_score = $2, human_note = $3, reviewed_by = $4, status = 'REVIEWED',
               needs_human_review = FALSE WHERE id = $1""", response_id, body.score, body.note, user.name)
    return {"id": str(response_id), "status": "REVIEWED"}


class TutorMessage(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/tutor/{item_id}/messages")
async def tutor_message(item_id: uuid.UUID, body: TutorMessage, user: User = Depends(current_user)):
    if user.role != "STUDENT":
        raise HTTPException(403, "Students chat with the tutor")
    if not await db.pool.fetchval("SELECT 1 FROM items WHERE id = $1 AND status = 'APPROVED'", item_id):
        raise HTTPException(404, "Item not found")
    return await tutor.chat(user.id, str(item_id), body.message)


@router.get("/tutor/{item_id}")
async def tutor_session(item_id: uuid.UUID, user: User = Depends(current_user)):
    r = await db.pool.fetchrow("SELECT state, transcript FROM learning_sessions WHERE student_id = $1 AND item_id = $2",
                               user.id, item_id)
    return dict(r) if r else {"state": {"hint_level": 0, "attempts": 0, "misconceptions": []}, "transcript": []}


@router.get("/memory")
async def memory(student_id: str | None = None, user: User = Depends(current_user)):
    sid = user.id if user.role == "STUDENT" else student_id
    return [dict(r) for r in await db.pool.fetch(
        """SELECT m.id, m.student_id, m.kind, m.content, m.created_at, m.embed_model FROM student_memory m
           WHERE ($1::text IS NULL OR m.student_id = $1) AND m.student_id <> 'STU-EVAL'
           ORDER BY m.created_at DESC LIMIT 50""", sid)]


class CodeRun(BaseModel):
    item_id: uuid.UUID
    code: str = Field(min_length=1, max_length=20000)


@router.post("/sandbox/run")
async def run_code(body: CodeRun, user: User = Depends(current_user)):
    tests = await db.pool.fetchval("SELECT tests FROM items WHERE id = $1 AND item_type = 'CODE' AND status = 'APPROVED'",
                                   body.item_id)
    if tests is None:
        raise HTTPException(404, "Code item not found")
    return await sandbox.run_tests(body.code, tests)


@router.post("/evals/{suite}", status_code=202)
async def run_eval(suite: str, user: User = Depends(current_user)):
    require_teacher(user)
    if suite not in evals.SUITES:
        raise HTTPException(404, f"Unknown suite; choose one of {', '.join(evals.SUITES)}")
    run_id = await db.pool.fetchval("INSERT INTO eval_runs (suite) VALUES ($1) RETURNING id", suite)
    _spawn(evals.run_suite(run_id, suite))
    return {"runId": str(run_id)}


@router.get("/evals")
async def eval_runs(user: User = Depends(current_user)):
    require_teacher(user)
    return [dict(r) for r in await db.pool.fetch("SELECT * FROM eval_runs ORDER BY started_at DESC LIMIT 30")]


@router.get("/observability")
async def observability(hours: int = 24, user: User = Depends(current_user)):
    require_teacher(user)
    calls = await db.pool.fetch(
        """SELECT role, provider, model, count(*) AS calls, count(*) FILTER (WHERE NOT ok) AS failures,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok) AS p50_ms,
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok) AS p95_ms,
                  COALESCE(sum(input_tokens), 0) AS input_tokens, COALESCE(sum(output_tokens), 0) AS output_tokens,
                  COALESCE(sum(cost_usd), 0) AS cost_usd
           FROM llm_calls WHERE created_at > now() - make_interval(hours => $1)
           GROUP BY role, provider, model ORDER BY calls DESC""", hours)
    safety_rows = await db.pool.fetch(
        """SELECT category, action, count(*) AS events FROM safety_events
           WHERE created_at > now() - make_interval(hours => $1) GROUP BY category, action ORDER BY events DESC""", hours)
    recent_failures = await db.pool.fetch(
        "SELECT created_at, role, provider, model, error FROM llm_calls WHERE NOT ok ORDER BY id DESC LIMIT 10")
    queue = await db.pool.fetchval("SELECT count(*) FROM responses WHERE needs_human_review")
    return {"modelCalls": [dict(r) for r in calls], "safety": [dict(r) for r in safety_rows],
            "recentFailures": [dict(r) for r in recent_failures], "reviewQueue": queue,
            "providers": llm.status(), "embeddingProviders": embeddings.status()}


@router.post("/admin/reindex")
async def reindex(user: User = Depends(current_user)):
    require_teacher(user)
    return {"indexed": await rag.index_missing()}


@router.get("/search")
async def search(q: str, user: User = Depends(current_user)):
    require_teacher(user)
    return await rag.search(q, 5)
