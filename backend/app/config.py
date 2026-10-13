"""Runtime configuration from environment variables."""
import os


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, default).split(",") if p.strip()]


DB_DSN = os.getenv("DATABASE_URL", "postgresql://edu:edu@localhost:5437/edu")

LLM_PROVIDERS = _list("LLM_PROVIDERS", "bedrock,anthropic")
EMBEDDING_PROVIDERS = _list("EMBEDDING_PROVIDERS", "bedrock,voyage")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE") or None
EMBED_DIMENSIONS = 1024  # Titan Text Embeddings V2 and voyage-3.5 both support 1024

# Model tier per agent role: fast and cheap for high-volume checks, strongest where quality matters most.
ROLE_MODELS = {
    "safety": "claude-haiku-5-5",
    "tutor": "claude-sonnet-5-5",
    "scoring": "claude-sonnet-5-5",
    "authoring": "claude-opus-5-5",
    "judge": "claude-opus-5-5",
}
ROLE_EFFORT = {"safety": "low", "tutor": "low", "scoring": "medium", "authoring": "high", "judge": "medium"}

SANDBOX_URL = os.getenv("SANDBOX_URL", "http://localhost:8072")
SCORING_REVIEW_CONFIDENCE = float(os.getenv("SCORING_REVIEW_CONFIDENCE", "0.7"))
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "true") == "true"
