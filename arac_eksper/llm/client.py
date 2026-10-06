from typing import Protocol, TypeVar, Type
from pydantic import BaseModel
from openai import OpenAI
from arac_eksper.config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential

T = TypeVar('T', bound=BaseModel)

class LLMClient(Protocol):
    def parse_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T]) -> T:
        ...

class OpenAIClient:
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def parse_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T]) -> T:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set.")
            
        completion = self.client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=response_model,
        )
        return completion.choices[0].message.parsed
