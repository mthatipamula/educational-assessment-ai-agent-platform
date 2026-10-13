"""MCP server: exposes the platform's knowledge to any MCP client (Claude Desktop, other agents) over
streamable HTTP at /mcp. Read-only tools; answer keys are never exposed."""
from mcp.server.mcpserver import MCPServer

from . import db, rag

mcp = MCPServer("educational-assessment",
                instructions="Search learning standards and passages, read approved assessment items, and summarize "
                             "student progress. Read-only; answer keys are never returned.")


@mcp.tool(description="Semantic search over learning standards and reading passages.")
async def search_standards(query: str) -> list[dict]:
    found = await rag.search(query, 5)
    return [{"source": f"{r['source_type']}:{r['source_id']}", "content": r["content"]} for r in found["results"]]


@mcp.tool(description="List approved assessment items for a standard code (without answer keys).")
async def list_items(standard_code: str) -> list[dict]:
    rows = await db.pool.fetch(
        "SELECT id, item_type, difficulty, stem, choices FROM items WHERE standard_code = $1 AND status = 'APPROVED'",
        standard_code)
    return [{**dict(r), "id": str(r["id"])} for r in rows]


@mcp.tool(description="Summarize a student's scored work and the tutor's notes about them.")
async def student_progress(student_id: str) -> dict:
    scores = await db.pool.fetch(
        """SELECT i.standard_code, COALESCE(r.human_score, r.ai_score) AS score, r.max_score, r.created_at
           FROM responses r JOIN items i ON i.id = r.item_id WHERE r.student_id = $1 AND r.status IN ('SCORED', 'REVIEWED')
           ORDER BY r.created_at DESC LIMIT 20""", student_id)
    notes = await db.pool.fetch(
        "SELECT kind, content FROM student_memory WHERE student_id = $1 ORDER BY created_at DESC LIMIT 10", student_id)
    return {"scores": [{**dict(r), "score": float(r["score"] or 0), "max_score": float(r["max_score"] or 0),
                        "created_at": r["created_at"].isoformat()} for r in scores],
            "tutorNotes": [dict(n) for n in notes]}
