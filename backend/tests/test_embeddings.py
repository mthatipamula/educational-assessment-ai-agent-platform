import asyncio

from app import config, db, embeddings


class _Pool:
    async def execute(self, *args):
        return None


def test_voyage_local_rate_limit_and_query_cache(monkeypatch):
    db.pool = _Pool()
    calls = []
    monkeypatch.setattr(config, "EMBEDDING_PROVIDERS", ["voyage"])
    monkeypatch.setattr(embeddings, "VOYAGE_RPM", 2)
    monkeypatch.setattr(embeddings, "_voyage", lambda texts, kind: calls.append(texts) or [[0.1] * 4 for _ in texts])
    embeddings._voyage_calls.clear()
    embeddings._query_cache.clear()

    asyncio.run(embeddings.embed(["ratios"], "query"))
    asyncio.run(embeddings.embed(["ratios"], "query"))          # served from cache, no request
    asyncio.run(embeddings.embed(["central idea"], "query"))
    assert len(calls) == 2
    try:                                                        # third distinct request in a minute: skipped locally
        asyncio.run(embeddings.embed(["proportional"], "query"))
        raised = False
    except embeddings.NoEmbeddingProvider:
        raised = True
    assert raised and len(calls) == 2
