import openai as _openai

from wrench.llm.base import LLMProvider, LLMResponse

_BASE_URL = "https://integrate.api.nvidia.com/v1"
_MODEL = "deepseek-ai/deepseek-v4-pro"


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, api_key: str):
        self._client = _openai.AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)

    async def ask(
        self,
        system_prompt: str,
        user_message: str,
        *,
        thinking: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=_MODEL,
            temperature=1,
            top_p=0.95,
            max_tokens=max(max_tokens, 16384),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            extra_body={"chat_template_kwargs": {"thinking": thinking}},
        )
        text = response.choices[0].message.content or ""
        return LLMResponse(
            text=text,
            provider=self.name,
            model=_MODEL,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        )

    async def health_check(self) -> bool:
        try:
            await self._client.chat.completions.create(
                model=_MODEL,
                max_tokens=5,
                messages=[{"role": "user", "content": "ping"}],
                extra_body={"chat_template_kwargs": {"thinking": False}},
            )
            return True
        except Exception:
            return False
