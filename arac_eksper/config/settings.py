from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    max_pages_per_hour: int = 40
    browser_profile_dir: str = "browser_profile"
    database_url: str = "sqlite:///data/arac.db"
    openai_api_key: str = ""
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
