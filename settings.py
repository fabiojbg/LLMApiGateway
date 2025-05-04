import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    load_dotenv(override=True)
    fallback_provider: str | None = os.getenv("FALLBACK_PROVIDER")
    gateway_api_key: str | None = os.getenv("GATEWAY_API_KEY")
    log_file_limit: int | None = int(os.getenv("LOG_FILE_LIMIT", 15))
    gateway_port: int | None = int(os.getenv("GATEWAY_PORT", 9000))
    provider_injection_enabled: bool = os.getenv("PROVIDER_INJECTION_ENABLED", "true").lower() == "true"
    log_chat_messages: bool = os.getenv("LOG_CHAT_ENABLED", "true").lower() == "true"
    
settings = Settings()