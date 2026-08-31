import os
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env file from the project root (assuming run.py is in the root)
# Adjust the path if the execution context changes
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path, override=False)

class Settings(BaseSettings):
    # It's generally better practice to load .env once at the start
    # and access variables directly via os.getenv within the class definition
    # or use Pydantic's built-in .env file handling.
    # Sticking closer to original for now, but consider refactoring this.

    fallback_provider: str = os.getenv("FALLBACK_PROVIDER", "openrouter")
    gateway_api_key: str | None = os.getenv("GATEWAY_API_KEY")
    log_file_limit: int = int(os.getenv("LOG_FILE_LIMIT", 15)) # Provide default directly
    gateway_port: int = int(os.getenv("GATEWAY_PORT", 9100)) # Provide default directly
    provider_injection_enabled: bool = os.getenv("PROVIDER_INJECTION_ENABLED", "true").lower() == "true"
    log_chat_messages: bool = os.getenv("LOG_CHAT_ENABLED", "true").lower() == "true"
    log_chat_request_max_chars: int = int(
        os.getenv("LOG_CHAT_REQUEST_MAX_CHARS", 1_048_576)
    )
    log_chat_response_max_chars: int = int(
        os.getenv("LOG_CHAT_RESPONSE_MAX_CHARS", 1_048_576)
    )
    # Add CORS settings
    cors_allow_origins_str: str | None = os.getenv("CORS_ALLOW_ORIGINS") # Load as string

    @property
    def cors_allow_origins(self) -> list[str] | None:
        """Parses the comma-separated CORS origins string into a list."""
        if self.cors_allow_origins_str:
            return [origin.strip() for origin in self.cors_allow_origins_str.split(",") if origin.strip()]
        return None # Return None if env var is not set or empty

    # Add debug mode setting
    debug_mode: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    gateway_host: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    http_connect_timeout: float = float(os.getenv("HTTP_CONNECT_TIMEOUT", 60))
    http_read_timeout: float = float(os.getenv("HTTP_READ_TIMEOUT", 300))
    http_write_timeout: float = float(os.getenv("HTTP_WRITE_TIMEOUT", 60))
    http_pool_timeout: float = float(os.getenv("HTTP_POOL_TIMEOUT", 60))
    http_stream_prefetch_max_bytes: int = int(
        os.getenv("HTTP_STREAM_PREFETCH_MAX_BYTES", 1_048_576)
    )
    http_stream_prefetch_max_events: int = int(
        os.getenv("HTTP_STREAM_PREFETCH_MAX_EVENTS", 256)
    )
    max_retry_count: int = Field(
        default=int(os.getenv("MAX_RETRY_COUNT", 10)), ge=0, le=100
    )
    max_retry_delay_seconds: int = Field(
        default=int(os.getenv("MAX_RETRY_DELAY_SECONDS", 120)), ge=1, le=3600
    )
    tokens_usage_retention_days: int = Field(
        default=int(os.getenv("TOKENS_USAGE_RETENTION_DAYS", 180)), ge=0, le=36_500
    )
    usage_records_max_limit: int = Field(
        default=int(os.getenv("USAGE_RECORDS_MAX_LIMIT", 500)), ge=1, le=10_000
    )
    usage_records_max_offset: int = Field(
        default=int(os.getenv("USAGE_RECORDS_MAX_OFFSET", 1_000_000)),
        ge=0,
    )


    # Example of Pydantic's .env handling (alternative approach)
    # class Config:
    #     env_file = '.env' # Relative to where the script is run
    #     env_file_encoding = 'utf-8'

# Create a single instance for the application to import
settings = Settings()
