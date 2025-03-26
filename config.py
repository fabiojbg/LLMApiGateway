import os
import logging
from logging.config import dictConfig
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    target_server_url: str | None = os.getenv("TARGET_SERVER_URL")
    target_api_key: str | None = os.getenv("TARGET_API_KEY")
    gateway_api_key: str | None = os.getenv("GATEWAY_API_KEY")

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
                'maxBytes': 1048576,
                'backupCount': 5,
                'formatter': 'json'
            }
        },
        'root': {
            'handlers': ['console', 'file'],
            'level': 'INFO'
        }
    })

settings = Settings()
