import json
import random
import time
from typing import Protocol, TypeVar, Type
from pydantic import BaseModel, ValidationError
from openai import OpenAI, RateLimitError, APIError, APITimeoutError, InternalServerError
from arac_eksper.config.settings import settings
import tenacity

T = TypeVar('T', bound=BaseModel)

class LLMUnavailable(Exception):
    pass

class LLMClient(Protocol):
    def parse_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T], model_name: str | None = None) -> T:
        ...

class OpenAIClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url
        )

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type((RateLimitError, APITimeoutError, InternalServerError)),
        wait=tenacity.wait_exponential_jitter(initial=2, max=20),
        stop=tenacity.stop_after_attempt(5),
        reraise=True
    )
    def _call_llm(self, messages, model_name):
        try:
            return self.client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"}
            )
        except RateLimitError as e:
            # Check if it's an out-of-quota error vs regular rate limit
            if "quota" in str(e).lower() or "insufficient_quota" in str(e).lower():
                raise LLMUnavailable("LLM kotası doldu.") from e
            raise

    def parse_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T], model_name: str | None = None) -> T:
        model = model_name or settings.llm_model_fast
        
        system_prompt_with_schema = system_prompt + f"\n\nLütfen aşağıdaki JSON şemasına uygun çıktı ver:\n{response_model.model_json_schema()}"
        
        messages = [
            {"role": "system", "content": system_prompt_with_schema},
            {"role": "user", "content": user_prompt}
        ]
        
        for attempt in range(2):
            try:
                completion = self._call_llm(messages, model)
                raw_content = completion.choices[0].message.content or ""
                
                # Temizle
                if raw_content.startswith("```json"):
                    raw_content = raw_content[7:]
                elif raw_content.startswith("```"):
                    raw_content = raw_content[3:]
                if raw_content.endswith("```"):
                    raw_content = raw_content[:-3]
                    
                raw_content = raw_content.strip()
                
                return response_model.model_validate_json(raw_content)
                
            except ValidationError as e:
                if attempt == 1:
                    raise e
                error_msg = f"JSON doğrulama hatası aldım:\n{str(e)}\n\nLütfen düzeltip sadece geçerli JSON gönder."
                messages.append({"role": "assistant", "content": raw_content})
                messages.append({"role": "user", "content": error_msg})
            except (RateLimitError, APITimeoutError, InternalServerError) as e:
                raise LLMUnavailable("LLM havuzuna erişilemiyor.") from e
            except tenacity.RetryError as e:
                raise LLMUnavailable("LLM havuzuna erişilemiyor.") from e
        
        raise LLMUnavailable("Beklenmeyen hata")
