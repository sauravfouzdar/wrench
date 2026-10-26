import asyncio
import json
import logging
import os
import re
import time

from wrench.exceptions import AllProvidersFailedError
from wrench.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_RATE_LIMIT_PHRASES = ("rate limit", "rate_limit", "too many requests", "429")
_SERVER_ERROR_PHRASES = ("server error", "service unavailable", "timeout", "5")


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in _RATE_LIMIT_PHRASES) or "429" in str(exc)


def _is_server_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in ("server error", "service unavailable", "timeout"))


class LLMRouter:
    CIRCUIT_TIMEOUT = 60.0

    def __init__(self, providers: list[LLMProvider], all_names: list[str] | None = None):
        self.providers = providers
        self._circuit_open: dict[str, float] = {}
        _active = {p.name for p in providers}
        self._not_configured: set[str] = set(all_names or []) - _active
        # preserve display order
        self._all_names: list[str] = all_names or [p.name for p in providers]

    async def ask(
        self, system_prompt: str, user_message: str, **kwargs
    ) -> LLMResponse:
        failures: list[str] = []
        for provider in self.providers:
            retry_after = self._circuit_open.get(provider.name)
            if retry_after and time.monotonic() < retry_after:
                failures.append(f"{provider.name}: circuit open")
                continue
            try:
                response = await provider.ask(system_prompt, user_message, **kwargs)
                self._circuit_open.pop(provider.name, None)
                return response
            except Exception as exc:
                if _is_rate_limit(exc) or _is_server_error(exc):
                    self._circuit_open[provider.name] = (
                        time.monotonic() + self.CIRCUIT_TIMEOUT
                    )
                    failures.append(f"{provider.name}: {exc} (circuit opened)")
                else:
                    logger.warning("Provider %s failed: %s", provider.name, exc)
                    failures.append(f"{provider.name}: {exc}")
        raise AllProvidersFailedError(
            "All providers failed:\n" + "\n".join(failures)
        )

    async def ask_json(
        self, system_prompt: str, user_message: str, **kwargs
    ) -> dict:
        response = await self.ask(system_prompt, user_message, **kwargs)
        text = _strip_code_fences(response.text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            retry_message = (
                user_message
                + "\n\nReply with only valid JSON, no prose or code fences."
            )
            response2 = await self.ask(system_prompt, retry_message, **kwargs)
            text2 = _strip_code_fences(response2.text)
            return json.loads(text2)

    HEALTH_CHECK_TIMEOUT = 8.0

    async def health_check_all(self) -> dict[str, str]:
        """Return status string per provider: 'healthy' | 'unhealthy' | 'circuit_open' | 'not_configured'."""
        active = {p.name: p for p in self.providers}
        now = time.monotonic()

        async def _check(provider: LLMProvider) -> bool:
            try:
                return await asyncio.wait_for(
                    provider.health_check(), timeout=self.HEALTH_CHECK_TIMEOUT
                )
            except (asyncio.TimeoutError, Exception):
                return False

        names = list(active.keys())
        results = await asyncio.gather(*[_check(active[n]) for n in names]) if names else []
        check_results: dict[str, bool] = dict(zip(names, results))

        status: dict[str, str] = {}
        for name in self._all_names:
            if name in self._not_configured:
                status[name] = "not_configured"
            elif name in self._circuit_open and now < self._circuit_open[name]:
                remaining = int(self._circuit_open[name] - now)
                status[name] = f"circuit_open:{remaining}s"
            elif check_results.get(name):
                status[name] = "healthy"
            else:
                status[name] = "unhealthy"

        return status


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def create_router() -> LLMRouter:
    from wrench.llm.anthropic import AnthropicProvider
    from wrench.llm.openai import OpenAIProvider
    from wrench.llm.deepseek import DeepSeekProvider
    from wrench.llm.gemini import GeminiProvider
    from wrench.llm.groq import GroqProvider

    order = os.getenv("LLM_PROVIDER_ORDER", "anthropic,openai,deepseek,gemini,groq")
    all_names = [n.strip() for n in order.split(",")]

    _factories = {
        "anthropic": ("ANTHROPIC_API_KEY", AnthropicProvider),
        "openai": ("OPENAI_API_KEY", OpenAIProvider),
        "deepseek": ("DEEPSEEK_API_KEY", DeepSeekProvider),
        "gemini": ("GEMINI_API_KEY", GeminiProvider),
        "groq": ("GROQ_API_KEY", GroqProvider),
    }

    providers: list[LLMProvider] = []
    for name in all_names:
        if name not in _factories:
            continue
        env_key, cls = _factories[name]
        api_key = os.getenv(env_key)
        if api_key:
            providers.append(cls(api_key=api_key))

    return LLMRouter(providers, all_names=all_names)
