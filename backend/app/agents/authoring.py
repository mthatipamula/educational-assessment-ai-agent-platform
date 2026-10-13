"""Item authoring agent: drafts a standards-aligned assessment item in several steps.

1. Research and draft (tool use): the model searches standards and passages (RAG), checks for near-duplicate
   items, then submits a draft through a strict `submit_item` tool.
2. Self-review: a separate review pass checks alignment, one correct answer, grade-level language, bias and
   rubric usability.
3. Revise once if the review finds problems.
4. Save as DRAFT. A teacher approves or rejects it; nothing reaches students without that step.
Each step is recorded on the run so the UI shows progress live.
"""
from __future__ import annotations

import json
import logging

from .. import db, llm, rag, telemetry

log = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 8

TOOLS = [
    {"name": "get_standard", "description": "Get a learning standard by code.", "strict": True,
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"],
                      "additionalProperties": False}},
    {"name": "search_knowledge", "description": "Semantic search over learning standards and reading passages.",
     "strict": True, "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                                      "required": ["query"], "additionalProperties": False}},
    {"name": "find_similar_items", "description": "Find existing items similar to a draft question, to avoid duplicates.",
     "strict": True, "input_schema": {"type": "object", "properties": {"question": {"type": "string"}},
                                      "required": ["question"], "additionalProperties": False}},
    {"name": "submit_item", "description": "Submit the finished item. Call exactly once, when the item is ready.",
     "strict": True,
     "input_schema": {"type": "object", "properties": {
         "stem": {"type": "string"},
         "choices": {"type": "array", "items": {"type": "string"},
                     "description": "Exactly 4 for MULTIPLE_CHOICE; empty otherwise"},
         "answer_key": {"type": "string", "description": "Correct letter, exemplar answer, or reference solution"},
         "rubric": {"type": "array", "items": {"type": "object", "properties": {
             "criterion": {"type": "string"}, "max_points": {"type": "integer"}, "descriptors": {"type": "string"}},
             "required": ["criterion", "max_points", "descriptors"], "additionalProperties": False}},
         "tests": {"type": "array", "description": "CODE items only: test cases for solve(...)", "items": {
             "type": "object", "properties": {"args_json": {"type": "string", "description": "JSON array of arguments"},
                                              "expected_json": {"type": "string", "description": "JSON expected value"}},
             "required": ["args_json", "expected_json"], "additionalProperties": False}},
         "rationale": {"type": "string", "description": "How the item measures the standard"}},
         "required": ["stem", "choices", "answer_key", "rubric", "tests", "rationale"], "additionalProperties": False}},
]

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "aligned_to_standard": {"type": "boolean"},
        "single_defensible_answer": {"type": "boolean"},
        "grade_appropriate_language": {"type": "boolean"},
        "free_of_bias_or_sensitive_content": {"type": "boolean"},
        "rubric_is_scorable": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "overall_quality": {"type": "integer", "description": "1 (unusable) to 5 (ready to use)"},
    },
    "required": ["aligned_to_standard", "single_defensible_answer", "grade_appropriate_language",
                 "free_of_bias_or_sensitive_content", "rubric_is_scorable", "issues", "overall_quality"],
    "additionalProperties": False,
}

SYSTEM = """You are an expert assessment developer writing items for K-12 students in the United States.
Write items that measure exactly the given standard at the requested difficulty, with clear, grade-appropriate
language, culturally neutral contexts, and no trick wording. Use the tools: look up the standard, search for
relevant passages or context, check for similar existing items, then call submit_item once.
- MULTIPLE_CHOICE: 4 choices, one correct, plausible distractors based on common misconceptions, all similar in
  length and detail; answer_key is the letter; rubric: one criterion "Correct choice" worth 1 point.
- CONSTRUCTED_RESPONSE: a rubric of 2-3 criteria with point descriptors; answer_key is an exemplar answer.
- CODE: ask for a Python function named solve; answer_key is a reference solution; give 4 tests including an edge case.
"""


async def _step(run_id: str, name: str, detail) -> None:
    # The jsonb codec serializes the value, so pass a plain (JSON-safe) object, not a JSON string.
    entry = json.loads(json.dumps([{"step": name, "detail": detail}], default=str))
    await db.pool.execute("UPDATE agent_runs SET steps = steps || $2::jsonb WHERE id = $1", run_id, entry)


async def _tool(name: str, args: dict) -> str:
    if name == "get_standard":
        r = await db.pool.fetchrow("SELECT * FROM standards WHERE code = $1", args["code"])
        return json.dumps(dict(r)) if r else "Standard not found"
    if name == "search_knowledge":
        found = await rag.search(args["query"], 4)
        return json.dumps({"method": found["method"], "results": [
            {"source": f"{x['source_type']}:{x['source_id']}", "content": x["content"][:1200]} for x in found["results"]]})
    if name == "find_similar_items":
        return json.dumps([{"stem": x["stem"][:200], "similarity": round(float(x["similarity"]), 3)}
                           for x in await rag.similar_items(args["question"])] or "No similar items found")
    return f"Unknown tool {name}"


async def _draft(run_id: str, request: dict, feedback: str | None, session: llm.ModelSession) -> dict:
    prompt = (f"Write a {request['difficulty']} {request['item_type']} item for standard {request['standard_code']}."
              + (f" Topic or context hint: {request['topic']}." if request.get("topic") else ""))
    if feedback:
        prompt += f"\n\nA reviewer found these problems in your previous draft. Fix them:\n{feedback}"
    messages = [{"role": "user", "content": prompt}]
    for _ in range(MAX_TOOL_ROUNDS):
        resp = await session.create(system=SYSTEM, messages=messages, tools=TOOLS, max_tokens=16000)
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        submitted = next((b for b in calls if b.name == "submit_item"), None)
        if submitted:
            await _step(run_id, "draft submitted", {"stem": submitted.input["stem"][:160]})
            return submitted.input
        if not calls:
            messages.append({"role": "user", "content": "Please call submit_item with the finished item."})
            continue
        results = []
        for b in calls:
            await _step(run_id, f"tool: {b.name}", b.input)
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": await _tool(b.name, b.input)})
        messages.append({"role": "user", "content": results})
    raise RuntimeError("The agent did not submit an item")


def _validate(item_type: str, draft: dict) -> list[str]:
    problems = []
    if item_type == "MULTIPLE_CHOICE" and not draft["rubric"]:
        # Multiple choice is scored by the key; a missing rubric is filled in rather than costing a revision.
        draft["rubric"] = [{"criterion": "Correct choice", "max_points": 1,
                            "descriptors": f"1 point for {draft['answer_key'].strip().upper()[:1]}."}]
    if item_type == "MULTIPLE_CHOICE":
        if len(draft["choices"]) != 4:
            problems.append("Multiple choice items need exactly 4 choices")
        if draft["answer_key"].strip().upper()[:1] not in "ABCD":
            problems.append("answer_key must be a letter A-D")
    if item_type == "CODE":
        if "def solve" not in draft["answer_key"]:
            problems.append("Reference solution must define solve(...)")
        if len(draft["tests"]) < 3:
            problems.append("Code items need at least 3 tests")
    if not draft["rubric"]:
        problems.append("Rubric is empty")
    return problems


async def run(run_id: str, request: dict) -> None:
    telemetry.trace_id_var.set((await db.pool.fetchval("SELECT trace_id FROM agent_runs WHERE id = $1", run_id)))
    try:
        author = llm.ModelSession("authoring")
        draft = await _draft(run_id, request, None, author)
        review = await _review(run_id, request, draft)
        problems = _validate(request["item_type"], draft) + (review["issues"] if not _passes(review) else [])
        if problems:
            await _step(run_id, "revising", problems)
            draft = await _draft(run_id, request, "\n".join(f"- {p}" for p in problems), llm.ModelSession("authoring"))
            review = await _review(run_id, request, draft)
            problems = _validate(request["item_type"], draft)
            if problems:
                raise RuntimeError("Draft still invalid: " + "; ".join(problems))

        tests = None
        if request["item_type"] == "CODE":
            tests = [{"args": json.loads(t["args_json"]), "expected": json.loads(t["expected_json"])} for t in draft["tests"]]
        item_id = await db.pool.fetchval(
            """INSERT INTO items (standard_code, item_type, difficulty, stem, choices, answer_key, rubric, tests,
                                  status, source, review_notes)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'DRAFT', 'AUTHORING_AGENT', $9) RETURNING id""",
            request["standard_code"], request["item_type"], request["difficulty"], draft["stem"],
            draft["choices"] if request["item_type"] == "MULTIPLE_CHOICE" else None,
            draft["answer_key"].strip().upper()[:1] if request["item_type"] == "MULTIPLE_CHOICE" else draft["answer_key"],
            draft["rubric"], tests, {"agent_review": review, "rationale": draft["rationale"], "served_by": author.served_by})
        await _step(run_id, "saved as draft for teacher review", {"item_id": str(item_id)})
        await db.pool.execute(
            "UPDATE agent_runs SET status = 'SUCCEEDED', output = $2, finished_at = now() WHERE id = $1",
            run_id, {"item_id": str(item_id), "review": review})
        await rag.index_missing()
    except Exception as err:  # noqa: BLE001 - record any failure on the run for the UI
        log.exception("Authoring run %s failed", run_id)
        await db.pool.execute(
            "UPDATE agent_runs SET status = 'FAILED', error = $2, finished_at = now() WHERE id = $1",
            run_id, f"{type(err).__name__}: {err}")


def _passes(review: dict) -> bool:
    return all(review[k] for k in ("aligned_to_standard", "single_defensible_answer", "grade_appropriate_language",
                                   "free_of_bias_or_sensitive_content", "rubric_is_scorable")) and review["overall_quality"] >= 4


async def _review(run_id: str, request: dict, draft: dict) -> dict:
    standard = await db.pool.fetchrow("SELECT * FROM standards WHERE code = $1", request["standard_code"])
    review = await llm.ModelSession("judge").json(
        REVIEW_SCHEMA, max_tokens=8000,
        system="You are a strict assessment reviewer. Judge the item against the checklist. Be specific about issues.",
        messages=[{"role": "user", "content": (
            f"Standard {standard['code']} (grade {standard['grade']}): {standard['description']}\n"
            f"Requested: {request['difficulty']} {request['item_type']}\n\nItem draft:\n{json.dumps(draft, indent=2)}")}])
    await _step(run_id, "self-review", {"quality": review["overall_quality"], "issues": review["issues"]})
    return review
