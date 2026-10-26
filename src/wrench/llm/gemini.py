import asyncio

import google.generativeai as genai

from wrench.llm.base import LLMProvider, LLMResponse

_MODEL = "gemini-2.5-pro"
_HEALTH_MODEL = "gemini-2.5-flash"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(_MODEL)
        self._health_model = genai.GenerativeModel(_HEALTH_MODEL)

    async def ask(
        self,
        system_prompt: str,
        user_message: str,
        *,
        thinking: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        prompt = f"{system_prompt}\n\n{user_message}"
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._model.generate_content(prompt)
        )
        text = response.text or ""
        usage = response.usage_metadata
        return LLMResponse(
            text=text,
            provider=self.name,
            model=_MODEL,
            input_tokens=getattr(usage, "prompt_token_count", 0),
            output_tokens=getattr(usage, "candidates_token_count", 0),
        )

    async def health_check(self) -> bool:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._health_model.generate_content("ping")
            )
            return True
        except Exception:
            return False
