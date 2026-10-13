"""Client for the code sandbox service, which runs untrusted student code in an isolated container."""
from __future__ import annotations

import httpx

from .. import config


async def run_tests(code: str, tests: list[dict]) -> dict:
    if len(code) > 20_000:
        return {"results": [{"passed": False, "error": "Code is too long"} for _ in tests], "error": "Code is too long"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{config.SANDBOX_URL}/run", json={"code": code, "tests": tests})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as err:
        return {"results": [{"passed": False, "error": "Sandbox unavailable"} for _ in tests],
                "error": f"Sandbox unavailable: {type(err).__name__}"}
