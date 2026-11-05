"""Minimal .env loader (KEY=VALUE lines) so the API key can live in an untracked .env file."""
import os
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    p = path or Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v and k not in os.environ:
            os.environ[k] = v
