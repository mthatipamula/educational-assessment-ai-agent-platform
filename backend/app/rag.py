"""Retrieval over standards and passages (pgvector), with a keyword fallback when no embedding provider works."""
from __future__ import annotations

import asyncio
import logging

from . import db, embeddings

log = logging.getLogger(__name__)


async def index_missing() -> int:
    """Embeds rows that have no vector yet: knowledge chunks, items and student memories (memories saved while no
    provider was available get their vectors later). Batched to use as few requests as possible."""
    done = 0
    for table, text_col in (("knowledge_chunks", "content"), ("items", "stem"), ("student_memory", "content")):
        rows = await db.pool.fetch(f"SELECT id, {text_col} AS text FROM {table} WHERE embedding IS NULL LIMIT 128")
        for i in range(0, len(rows), 64):
            batch = rows[i:i + 64]
            try:
                vectors, model = await embeddings.embed([r["text"] for r in batch])
            except embeddings.NoEmbeddingProvider as err:
                log.info("Indexing paused: %s", err)
                return done
            for r, v in zip(batch, vectors):
                await db.pool.execute(f"UPDATE {table} SET embedding = $2::vector, embed_model = $3 WHERE id = $1",
                                      r["id"], db.vector_literal(v), model)
            done += len(batch)
    if done:
        log.info("Indexed %d rows", done)
    return done


async def index_forever(interval_seconds: int = 120) -> None:
    """Background loop: picks up anything that couldn't be embedded earlier (e.g. after a rate limit)."""
    while True:
        try:
            await index_missing()
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("Background indexing failed")
        await asyncio.sleep(interval_seconds)


async def search(query: str, k: int = 5) -> dict:
    """Semantic search; falls back to Postgres full-text search so the app keeps working without embeddings."""
    try:
        [vec], model = await embeddings.embed([query], "query")
        rows = await db.pool.fetch(
            """SELECT source_type, source_id, content, 1 - (embedding <=> $1::vector) AS score
               FROM knowledge_chunks WHERE embed_model = $2 ORDER BY embedding <=> $1::vector LIMIT $3""",
            db.vector_literal(vec), model, k)
        if rows:
            return {"method": f"vector:{model}", "results": [dict(r) for r in rows]}
    except embeddings.NoEmbeddingProvider:
        pass
    rows = await db.pool.fetch(
        """SELECT source_type, source_id, content, ts_rank(tsv, websearch_to_tsquery('english', $1)) AS score
           FROM knowledge_chunks WHERE tsv @@ websearch_to_tsquery('english', $1) ORDER BY score DESC LIMIT $2""",
        query, k)
    if not rows:  # broad fallback: any word
        rows = await db.pool.fetch(
            """SELECT source_type, source_id, content, 0.0 AS score FROM knowledge_chunks
               WHERE content ILIKE ANY($1) LIMIT $2""", [f"%{w}%" for w in query.split() if len(w) > 3] or ["%"], k)
    return {"method": "keyword", "results": [dict(r) for r in rows]}


async def similar_items(text: str, k: int = 3) -> list[dict]:
    """Near-duplicate check for new items (cosine similarity on stems)."""
    try:
        [vec], model = await embeddings.embed([text], "query")
    except embeddings.NoEmbeddingProvider:
        return []
    rows = await db.pool.fetch(
        """SELECT id, stem, status, 1 - (embedding <=> $1::vector) AS similarity FROM items
           WHERE embed_model = $2 ORDER BY embedding <=> $1::vector LIMIT $3""", db.vector_literal(vec), model, k)
    return [dict(r) for r in rows]
