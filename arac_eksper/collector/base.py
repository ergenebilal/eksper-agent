from typing import Protocol, Literal, Optional
from pydantic import BaseModel

class FetchResult(BaseModel):
    status: Literal["OK", "BLOCKED", "NOT_FOUND", "ERROR", "RATE_LIMITED"]
    html: Optional[str] = None
    final_url: str
    saved_path: Optional[str] = None
    note: Optional[str] = None

class Collector(Protocol):
    async def fetch_list(self, url: str) -> FetchResult:
        ...
        
    async def fetch_detail(self, url: str) -> FetchResult:
        ...
