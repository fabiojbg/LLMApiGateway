import os
from dotenv import load_dotenv
import logging
from logging.config import dictConfig
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    load_dotenv()
    fallback_provider: str | None = os.getenv("FALLBACK_PROVIDER")
    gateway_api_key: str | None = os.getenv("GATEWAY_API_KEY")
    gateway_port: int | None = int(9000)
    log_file_limit: int | None = int(os.getenv("LOG_FILE_LIMIT", 15))
    provider_injection_enabled: bool = os.getenv("PROVIDER_INJECTION_ENABLED", "true").lower() == "true"
    log_chat_messages: bool = os.getenv("LOG_CHAT_ENABLED", "true").lower() == "true"
    
    #keys used by v1 api that uses openrouter_provider_mapping.json
    target_server_url: str | None = os.getenv("TARGET_SERVER_URL")
    target_api_key: str | None = os.getenv("TARGET_API_KEY")

    class Config:
        case_sensitive = True

def configure_logging():
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    dictConfig({
        'version': 1,
        'formatters': {
            'json': {
                'format': '%(asctime)s %(levelname)s %(message)s',
                'class': 'pythonjsonlogger.jsonlogger.JsonFormatter'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'json'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'logs/gateway.log',
                'maxBytes': 256000,
                'backupCount': 5,
                'formatter': 'json'
            }
        },
        'root': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG'
        },
        'loggers': {
            'httpcore': {
                'level': 'WARNING',
                'handlers': ['console', 'file'],
                'propagate': False
            }
        }
    })

settings = Settings()
