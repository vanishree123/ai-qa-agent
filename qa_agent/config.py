"""Settings loaded from .env, with a guard that keeps the agent pointed at safe targets."""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    target_url: str

    @property
    def target_host(self) -> str:
        return urlparse(self.target_url).hostname or ""


def load_settings(target_override: str | None = None) -> Settings:
    s = Settings(
        api_key=os.getenv("LLAMA_API_KEY", "").strip(),
        base_url=os.getenv("LLAMA_BASE_URL", "https://api.llama.com/compat/v1/").strip(),
        model=os.getenv("LLAMA_MODEL", "Llama-3.3-70B-Instruct").strip(),
        target_url=(target_override or os.getenv("TARGET_URL", "http://127.0.0.1:5000")).strip().rstrip("/"),
    )
    if s.target_host not in LOCAL_HOSTS and os.getenv("ALLOW_REMOTE_TARGET") != "1":
        raise SystemExit(
            f"Refusing to test non-local target '{s.target_host}'. "
            "Generated scripts are only run against localhost unless ALLOW_REMOTE_TARGET=1 "
            "and you own/are authorized to test that system."
        )
    return s
