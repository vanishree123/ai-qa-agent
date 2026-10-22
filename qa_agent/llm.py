"""Meta Llama API client (OpenAI-compatible endpoint at https://api.llama.com/compat/v1/)."""
import json
import re

from openai import BadRequestError, OpenAI

from .config import Settings


class MetaLlamaClient:
    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise SystemExit("LLAMA_API_KEY is empty. Add it to .env, or use --offline.")
        self.model = settings.model
        # Long timeout: local models can take minutes to load and answer on modest hardware.
        self.client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=900)

    def chat(self, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4000,
             json_mode: bool = False) -> str:
        kwargs = dict(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except BadRequestError:
            if not json_mode:
                raise
            kwargs.pop("response_format")  # provider doesn't support JSON mode; fall back to plain text
            resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list().data]


_FENCE = re.compile(r"```(?:[a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Return the first fenced code block, or the raw text if there is none."""
    m = _FENCE.search(text)
    return (m.group(1) if m else text).strip() + "\n"


def extract_json(text: str):
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    candidate = extract_code(text) if "```" in text else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = min((i for i in (candidate.find("["), candidate.find("{")) if i != -1), default=-1)
        end = max(candidate.rfind("]"), candidate.rfind("}"))
        if start == -1 or end <= start:
            raise
        return json.loads(candidate[start : end + 1])
