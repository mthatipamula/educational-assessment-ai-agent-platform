#!/usr/bin/env bash
# Local stack: PostgreSQL + pgvector, API and agents, code sandbox, web app on http://localhost:8070.
#   ./scripts/dev.sh start          build and start
#   ./scripts/dev.sh stop           stop (data kept)
#   ./scripts/dev.sh status         health and model providers
#   ./scripts/dev.sh logs [service] follow logs
#   ./scripts/dev.sh evals SUITE    run an evaluation suite: safety | scoring | tutor | authoring (calls Claude)
#   ./scripts/dev.sh test           backend unit tests
#   ./scripts/dev.sh reset          delete all local data
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-start}" in
  start)
    if [ ! -f .env ]; then
      cp .env.example .env
      echo "Created .env from .env.example. Add ANTHROPIC_API_KEY and VOYAGE_API_KEY to it (Bedrock uses your AWS profile)."
    fi
    grep -q '^ANTHROPIC_API_KEY=.\+' .env || echo "Note: ANTHROPIC_API_KEY is empty in .env; agents work only if Bedrock is reachable."
    grep -q '^VOYAGE_API_KEY=.\+' .env || echo "Note: VOYAGE_API_KEY is empty in .env; search uses keywords unless Titan on Bedrock is reachable."
    docker compose up -d --build
    printf 'Waiting for the API'
    for _ in $(seq 1 90); do curl -sf localhost:8071/health >/dev/null && break; printf '.'; sleep 2; done
    echo
    docker compose ps --format 'table {{.Service}}\t{{.Status}}'
    cat <<MSG

Web app:   http://localhost:8070      (sign in as Ms. Rivera, Maya or Leo)
API:       http://localhost:8071/docs
MCP:       http://localhost:8071/mcp  (streamable HTTP)
MSG
    ;;
  stop)   docker compose stop ;;
  status)
    docker compose ps --format 'table {{.Service}}\t{{.Status}}'
    curl -s -H 'X-API-Key: teacher-key' localhost:8071/api/status | python3 -m json.tool ;;
  logs)   docker compose logs -f --tail 100 ${2:+"$2"} ;;
  evals)  docker compose exec backend python -m app.evals "${2:?suite: safety | scoring | tutor | authoring}" ;;
  test)   docker compose run --rm --no-deps -v "$PWD/backend/tests:/app/tests:ro" backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests" ;;
  reset)
    read -r -p "Delete all local data? [y/N] " answer
    [ "$answer" = y ] || [ "$answer" = Y ] || { echo "Aborted."; exit 1; }
    docker compose down -v ;;
  *) echo "usage: $0 [start|stop|status|logs [service]|evals SUITE|test|reset]"; exit 1 ;;
esac
