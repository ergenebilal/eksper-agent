from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    max_pages_per_hour: int = 40
    browser_profile_dir: str = "browser_profile"
    database_url: str = "sqlite:///data/arac.db"
    openai_api_key: str = ""
    
    llm_base_url: str = "http://127.0.0.1:8999/v1"
    llm_api_key: str = "sk-placeholder"
    llm_model_fast: str = "fast-model"
    llm_model_strong: str = "strong-model"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
