"""Educational Assessment AI Agent Platform: API, agents and MCP server."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import db, rag, telemetry
from .mcp_server import mcp
from .routes.api import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")
mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True, host="0.0.0.0")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.connect()
    indexing = asyncio.create_task(rag.index_forever())  # embeds the knowledge base and anything missed later
    async with mcp.session_manager.run():
        yield
    indexing.cancel()
    await db.pool.close()


app = FastAPI(title="Educational Assessment AI Agent Platform", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def trace(request: Request, call_next):
    tid = telemetry.new_trace()
    response = await call_next(request)
    response.headers["X-Trace-Id"] = tid
    return response


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse({"status": 500, "detail": "Something went wrong", "trace": telemetry.trace_id_var.get()}, 500)


@app.get("/health")
async def health():
    await db.pool.fetchval("SELECT 1")
    return {"status": "UP"}


app.include_router(router)
app.mount("/mcp", mcp_app)
