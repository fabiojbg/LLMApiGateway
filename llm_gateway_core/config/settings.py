import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env file from the project root (assuming run.py is in the root)
# Adjust the path if the execution context changes
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path, override=True)

class Settings(BaseSettings):
    # It's generally better practice to load .env once at the start
    # and access variables directly via os.getenv within the class definition
    # or use Pydantic's built-in .env file handling.
    # Sticking closer to original for now, but consider refactoring this.

    fallback_provider: str | None = os.getenv("FALLBACK_PROVIDER")
    gateway_api_key: str | None = os.getenv("GATEWAY_API_KEY")
    log_file_limit: int = int(os.getenv("LOG_FILE_LIMIT", 15)) # Provide default directly
    gateway_port: int = int(os.getenv("GATEWAY_PORT", 9000)) # Provide default directly
    provider_injection_enabled: bool = os.getenv("PROVIDER_INJECTION_ENABLED", "true").lower() == "true"
    log_chat_messages: bool = os.getenv("LOG_CHAT_ENABLED", "true").lower() == "true"
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


    # Example of Pydantic's .env handling (alternative approach)
    # class Config:
    #     env_file = '.env' # Relative to where the script is run
    #     env_file_encoding = 'utf-8'

# Create a single instance for the application to import
settings = Settings()
