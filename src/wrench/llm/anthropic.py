import anthropic as _anthropic

from wrench.llm.base import LLMProvider, LLMResponse

_MODEL = "claude-opus-4-5"
_HEALTH_MODEL = "claude-haiku-4-5"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str):
        self._client = _anthropic.AsyncAnthropic(api_key=api_key)

    async def ask(
        self,
        system_prompt: str,
        user_message: str,
        *,
        thinking: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": _MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        if thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8000}
            kwargs["max_tokens"] = max(max_tokens, 10000)

        response = await self._client.messages.create(**kwargs)
        text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        return LLMResponse(
            text=text,
            provider=self.name,
            model=_MODEL,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def health_check(self) -> bool:
        try:
            await self._client.messages.create(
                model=_HEALTH_MODEL,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False
