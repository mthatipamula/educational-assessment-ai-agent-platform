"""The gateway skips a provider that refuses access (e.g. Bedrock blocked) and serves from the next one."""
import asyncio
from types import SimpleNamespace

import anthropic
import httpx2

from app import db, llm


class _Pool:
    async def execute(self, *args):
        return None


def _error(cls, status):
    request = httpx2.Request("POST", "https://example.invalid/v1/messages")
    return cls("denied", response=httpx2.Response(status, request=request), body=None)


class _Failing:
    def __init__(self, err):
        self.messages = SimpleNamespace(create=self._create)
        self.err = err

    async def _create(self, **kwargs):
        raise self.err


class _Working:
    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)
        self.models = []

    async def _create(self, **kwargs):
        self.models.append(kwargs["model"])
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                               content=[SimpleNamespace(type="text", text="ok")])


def test_falls_back_and_cools_down(monkeypatch):
    db.pool = _Pool()
    bedrock = llm.Provider("bedrock", _Failing(_error(anthropic.NotFoundError, 404)), "anthropic.")
    direct_client = _Working()
    direct = llm.Provider("anthropic", direct_client)
    monkeypatch.setattr(llm, "PROVIDERS", [bedrock, direct])

    session = llm.ModelSession("tutor")
    resp = asyncio.run(session.create(messages=[{"role": "user", "content": "hi"}]))
    assert llm.text_of(resp) == "ok"
    assert session.served_by == "anthropic:claude-sonnet-5-5"
    assert direct_client.models == ["claude-sonnet-5-5"]          # first-party ID, no Bedrock prefix
    assert not bedrock.available                                  # skipped until the cool-down ends

    asyncio.run(llm.ModelSession("tutor").create(messages=[{"role": "user", "content": "again"}]))
    assert len(direct_client.models) == 2


def test_bad_requests_are_not_hidden_by_fallback(monkeypatch):
    db.pool = _Pool()
    err = _error(anthropic.BadRequestError, 400)
    monkeypatch.setattr(llm, "PROVIDERS", [llm.Provider("anthropic", _Failing(err))])
    try:
        asyncio.run(llm.ModelSession("tutor").create(messages=[]))
        raised = False
    except anthropic.BadRequestError:
        raised = True
    assert raised


class _NoCredentials:
    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        raise TypeError("Could not resolve authentication method")


def test_unconfigured_provider_is_skipped_not_fatal(monkeypatch):
    db.pool = _Pool()
    working = _Working()
    monkeypatch.setattr(llm, "PROVIDERS", [llm.Provider("anthropic", _NoCredentials()), llm.Provider("other", working)])
    resp = asyncio.run(llm.ModelSession("safety").create(messages=[{"role": "user", "content": "hi"}]))
    assert llm.text_of(resp) == "ok"


def test_no_provider_raises_clear_error(monkeypatch):
    db.pool = _Pool()
    monkeypatch.setattr(llm, "PROVIDERS", [llm.Provider("anthropic", _NoCredentials())])
    try:
        asyncio.run(llm.ModelSession("safety").create(messages=[]))
        raised = None
    except llm.NoProviderAvailable as err:
        raised = err
    assert raised is not None
