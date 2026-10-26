from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def ask(
        self,
        system_prompt: str,
        user_message: str,
        *,
        thinking: bool = False,
        max_tokens: int = 4096,
    ) -> LLMResponse: ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable. Must not raise."""
        ...
