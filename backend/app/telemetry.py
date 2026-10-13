"""Observability: one row per model or embedding call, plus safety events. Trace IDs tie a request together."""
import contextvars
import logging
import uuid

from . import db

log = logging.getLogger("telemetry")
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

# USD per million tokens (input, output). Bedrock is billed by AWS at its own rates; this is an estimate.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def new_trace() -> str:
    tid = uuid.uuid4().hex[:16]
    trace_id_var.set(tid)
    return tid


def estimate_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    base = model.removeprefix("anthropic.")
    if base not in PRICES or input_tokens is None:
        return None
    pin, pout = PRICES[base]
    return (input_tokens * pin + (output_tokens or 0) * pout) / 1_000_000


async def record_call(role: str, provider: str, model: str, ok: bool, latency_ms: int,
                      input_tokens: int | None = None, output_tokens: int | None = None, error: str | None = None) -> None:
    cost = estimate_cost(model, input_tokens, output_tokens)
    log.info('{"event":"model_call","trace":"%s","role":"%s","provider":"%s","model":"%s","ok":%s,"ms":%d}',
             trace_id_var.get(), role, provider, model, str(ok).lower(), latency_ms)
    try:
        await db.pool.execute(
            """INSERT INTO llm_calls (trace_id, role, provider, model, ok, error, latency_ms, input_tokens, output_tokens, cost_usd)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
            trace_id_var.get(), role, provider, model, ok, (error or "")[:500] or None, latency_ms,
            input_tokens, output_tokens, cost)
    except Exception:  # noqa: BLE001 - telemetry must never break the request
        log.exception("Could not record model call")


async def record_safety(surface: str, category: str, action: str, detail: str = "", student_id: str | None = None) -> None:
    try:
        await db.pool.execute(
            "INSERT INTO safety_events (trace_id, student_id, surface, category, action, detail) VALUES ($1, $2, $3, $4, $5, $6)",
            trace_id_var.get(), student_id, surface, category, action, detail[:500])
    except Exception:  # noqa: BLE001
        log.exception("Could not record safety event")
