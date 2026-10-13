"""Embeddings with provider fallback: Amazon Titan Text Embeddings V2 on Bedrock first, then Voyage AI.

Both produce 1024-dimension vectors, so one pgvector column fits either. Vectors from different models are NOT
comparable, so every stored vector records its model, and searches only compare vectors from the same model.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time

from . import config, telemetry

log = logging.getLogger(__name__)
TITAN_MODEL = "amazon.titan-embed-text-v2:0"
VOYAGE_MODEL = "voyage-3.5"
_disabled_until: dict[str, float] = {}
_last_error: dict[str, str] = {}
# Voyage accounts without a payment method allow only 3 requests per minute: stay under it client-side
# instead of spending a request to find out.
VOYAGE_RPM = int(os.getenv("VOYAGE_RPM", "3"))
_voyage_calls: collections.deque[float] = collections.deque()
_query_cache: "collections.OrderedDict[tuple[str, str], tuple[list[float], str]]" = collections.OrderedDict()
QUERY_CACHE_SIZE = 256


def _voyage_budget_left() -> bool:
    now = time.monotonic()
    while _voyage_calls and now - _voyage_calls[0] > 60:
        _voyage_calls.popleft()
    return len(_voyage_calls) < VOYAGE_RPM


class NoEmbeddingProvider(RuntimeError):
    pass


def _titan(texts: list[str]) -> list[list[float]]:
    import boto3  # noqa: PLC0415 - only needed when Bedrock is configured
    session = boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION)
    client = session.client("bedrock-runtime")
    out = []
    for text in texts:  # Titan embeds one text per request
        resp = client.invoke_model(modelId=TITAN_MODEL, body=json.dumps(
            {"inputText": text[:20000], "dimensions": config.EMBED_DIMENSIONS, "normalize": True}))
        out.append(json.loads(resp["body"].read())["embedding"])
    return out


def _voyage(texts: list[str], input_type: str) -> list[list[float]]:
    import voyageai  # noqa: PLC0415
    client = voyageai.Client()  # reads VOYAGE_API_KEY
    result = client.embed(texts, model=VOYAGE_MODEL, input_type=input_type, output_dimension=config.EMBED_DIMENSIONS)
    return result.embeddings


async def embed(texts: list[str], input_type: str = "document") -> tuple[list[list[float]], str]:
    """Returns (vectors, model name). input_type is "document" for stored text, "query" for searches."""
    cache_key = (texts[0], input_type) if len(texts) == 1 and input_type == "query" else None
    if cache_key and cache_key in _query_cache:
        _query_cache.move_to_end(cache_key)
        vec, model = _query_cache[cache_key]
        return [vec], model

    errors = []
    for provider in config.EMBEDDING_PROVIDERS:
        if time.monotonic() < _disabled_until.get(provider, 0):
            continue
        if provider == "voyage" and not _voyage_budget_left():
            errors.append("voyage: local rate limit")
            continue
        model = TITAN_MODEL if provider == "bedrock" else VOYAGE_MODEL
        start = time.monotonic()
        try:
            if provider == "bedrock":
                vectors = await asyncio.to_thread(_titan, texts)
            elif provider == "voyage":
                _voyage_calls.append(time.monotonic())
                vectors = await asyncio.to_thread(_voyage, texts, input_type)
            else:
                continue
        except Exception as err:  # noqa: BLE001 - any failure falls through to the next provider
            ms = int((time.monotonic() - start) * 1000)
            await telemetry.record_call("embedding", provider, model, False, ms, error=f"{type(err).__name__}: {err}")
            rate_limited = "ratelimit" in type(err).__name__.lower() or "throttl" in type(err).__name__.lower()
            _disabled_until[provider] = time.monotonic() + (20 if rate_limited else 300)
            _last_error[provider] = f"{type(err).__name__}: {str(err)[:200]}"
            errors.append(f"{provider}: {type(err).__name__}")
            log.warning("Embedding provider %s failed (%s); trying next", provider, type(err).__name__)
            continue
        ms = int((time.monotonic() - start) * 1000)
        await telemetry.record_call("embedding", provider, model, True, ms)
        if cache_key:
            _query_cache[cache_key] = (vectors[0], model)
            if len(_query_cache) > QUERY_CACHE_SIZE:
                _query_cache.popitem(last=False)
        return vectors, model
    raise NoEmbeddingProvider("No embedding provider available: " + ", ".join(errors or ["all cooling down"]))


def status() -> list[dict]:
    now = time.monotonic()
    return [{"provider": p, "available": now >= _disabled_until.get(p, 0), "lastError": _last_error.get(p, "")}
            for p in config.EMBEDDING_PROVIDERS]
