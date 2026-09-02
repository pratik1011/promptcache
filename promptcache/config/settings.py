import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Load a local .env without requiring a framework.
def _load_dotenv() -> None:
    path = Path(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\\\""))

_load_dotenv()

def _json(name: str, default: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = os.getenv(name)
    return json.loads(raw) if raw else default

@dataclass(frozen=True)
class Settings:
    port: int
    api_key: str
    similarity_threshold: float
    cache_ttl_seconds: int
    providers: list[dict[str, Any]]
    routes: list[dict[str, Any]]
    data_file: str

def load_settings() -> Settings:
    providers = _json("PROVIDERS_JSON", [{"id":"demo","type":"generic","baseUrl":"mock://local","model":"demo","inputCostPerMillion":1,"outputCostPerMillion":2}])
    return Settings(int(os.getenv("PORT",8787)), os.getenv("ADMIN_API_KEY","development-only"), float(os.getenv("CACHE_SIMILARITY_THRESHOLD",.92)), int(os.getenv("CACHE_TTL_SECONDS",86400)), providers, _json("ROUTES_JSON", [{"maxComplexity":10,"provider":providers[0]["id"]}]), os.getenv("DATA_FILE",".data/store.json"))


