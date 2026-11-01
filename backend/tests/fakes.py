"""A scripted stand-in for the Groq SDK, so tests need no key or network."""
import json
from types import SimpleNamespace

from app.config import Settings
from app.llm.client import LLMClient


class FakeStatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeSDK:
    """Plays back a script: each item is a reply (str or dict → JSON) or an exception to raise."""

    def __init__(self, script, models=("openai/gpt-oss-20b", "openai/gpt-oss-120b")):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(
            data=[SimpleNamespace(id=m) for m in models]))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError(f"Unexpected extra LLM call #{len(self.calls)}")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        content = json.dumps(item) if isinstance(item, dict) else item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


def make_llm(script, **kw) -> LLMClient:
    settings = Settings(groq_api_key="test", llm_max_retries=3, database_url="sqlite:///./test.db")
    return LLMClient(settings, sdk=FakeSDK(script, **kw))
