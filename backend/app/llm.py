"""Claude gateway with provider fallback: Amazon Bedrock first, then the Anthropic API.

Both providers use the official Anthropic SDK and the same Messages API, so agents are written once. Model IDs
differ only by Bedrock's `anthropic.` prefix. A provider that refuses with an access-type error (account blocked,
model not enabled, missing key) is skipped for a cool-down period instead of being retried on every call.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import anthropic
from anthropic import AsyncAnthropic, AsyncAnthropicBedrockMantle

from . import config, telemetry

log = logging.getLogger(__name__)
COOL_DOWN_SECONDS = 300


class NoProviderAvailable(RuntimeError):
    pass


class ModelRefusal(RuntimeError):
    pass


@dataclass
class Provider:
    name: str
    client: object
    prefix: str = ""
    disabled_until: float = 0.0
    last_error: str = ""

    def model(self, role: str) -> str:
        return self.prefix + config.ROLE_MODELS[role]

    @property
    def available(self) -> bool:
        return time.monotonic() >= self.disabled_until


def _build() -> list[Provider]:
    providers = []
    for name in config.LLM_PROVIDERS:
        try:
            if name == "bedrock":
                providers.append(Provider("bedrock", AsyncAnthropicBedrockMantle(
                    aws_region=config.AWS_REGION, aws_profile=config.AWS_PROFILE, max_retries=1, timeout=120), "anthropic."))
            elif name == "anthropic":
                # Credentials come from ANTHROPIC_API_KEY (or an `ant auth login` profile); never hardcoded.
                providers.append(Provider("anthropic", AsyncAnthropic(max_retries=2, timeout=300)))
        except Exception as err:  # noqa: BLE001 - a misconfigured provider must not stop the app from starting
            log.warning("Provider %s not configured: %s", name, err)
    return providers


PROVIDERS = _build()


def status() -> list[dict]:
    now = time.monotonic()
    return [{"provider": p.name, "available": p.available, "retryInSeconds": max(0, int(p.disabled_until - now)),
             "lastError": p.last_error} for p in PROVIDERS]


def _is_access_error(err: Exception) -> bool:
    """Errors that mean "this provider can't serve us right now", as opposed to a bad request we built."""
    if isinstance(err, (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)):
        return True
    if isinstance(err, anthropic.BadRequestError):
        msg = str(err).lower()
        return any(s in msg for s in ("not allowed", "access", "not authorized", "credit balance", "model"))
    return False


@dataclass
class ModelSession:
    """Pins one provider for a multi-turn exchange, so the whole conversation (including thinking blocks)
    stays on the model that produced it."""
    role: str
    provider: Provider | None = None
    calls: list[dict] = field(default_factory=list)

    async def create(self, **kwargs) -> anthropic.types.Message:
        candidates = [self.provider] if self.provider else [p for p in PROVIDERS if p.available]
        if not candidates:
            raise NoProviderAvailable("No Claude provider is available (check AWS access or ANTHROPIC_API_KEY)")
        last: Exception | None = None
        for p in candidates:
            model = p.model(self.role)
            params = {"model": model, "max_tokens": 16000, **kwargs}
            params.setdefault("output_config", {})
            params["output_config"] = {"effort": config.ROLE_EFFORT[self.role], **params["output_config"]}
            start = time.monotonic()
            try:
                resp = await p.client.messages.create(**params)
            except TypeError as err:
                # Raised by the SDK before any request when no credentials are configured (e.g. no API key).
                await telemetry.record_call(self.role, p.name, model, False, 0, error=f"not configured: {err}")
                p.disabled_until = time.monotonic() + COOL_DOWN_SECONDS
                p.last_error = "not configured (no credentials)"
                last = err
                continue
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as err:
                ms = int((time.monotonic() - start) * 1000)
                await telemetry.record_call(self.role, p.name, model, False, ms, error=f"{type(err).__name__}: {err}")
                last = err
                if self.provider:            # pinned mid-conversation: don't switch models silently
                    raise
                if _is_access_error(err):
                    p.disabled_until = time.monotonic() + COOL_DOWN_SECONDS
                    p.last_error = f"{type(err).__name__}: {str(err)[:200]}"
                    log.warning("Provider %s unavailable (%s); falling back", p.name, type(err).__name__)
                    continue
                if isinstance(err, (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)):
                    continue                 # transient on this provider: try the next one
                raise                        # a genuine bad request: surface it
            ms = int((time.monotonic() - start) * 1000)
            await telemetry.record_call(self.role, p.name, model, True, ms,
                                        resp.usage.input_tokens, resp.usage.output_tokens)
            self.provider = p
            self.calls.append({"provider": p.name, "model": model, "ms": ms})
            if resp.stop_reason == "refusal":
                raise ModelRefusal(f"{model} declined the request")
            return resp
        raise NoProviderAvailable(f"All Claude providers failed: {type(last).__name__}: {last}") from last

    async def json(self, schema: dict, **kwargs) -> dict:
        """Structured output: the response is guaranteed to match `schema`."""
        cfg = {"format": {"type": "json_schema", "schema": schema}}
        resp = await self.create(output_config=cfg, **kwargs)
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    @property
    def served_by(self) -> str:
        return f"{self.provider.name}:{self.provider.model(self.role)}" if self.provider else "none"


def text_of(resp: anthropic.types.Message) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()
