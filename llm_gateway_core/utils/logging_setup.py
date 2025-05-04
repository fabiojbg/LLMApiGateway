import os
from dotenv import load_dotenv
import logging
from logging.config import dictConfig
from pydantic_settings import BaseSettings
from pythonjsonlogger.jsonlogger import JsonFormatter

class CustomJsonFormatter(JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        if 'taskName' in log_record:
            del log_record['taskName']

def configure_logging():
    # Create logs directory if it doesn't exist
    # Note: This assumes the script is run from the project root
    # If run from within llm_gateway_core, the path might need adjustment
    # For now, keeping it relative to the expected execution context (root)
    os.makedirs('logs', exist_ok=True)

    dictConfig({
        'version': 1,
        'formatters': {
            'json': {
                'fmt': '%(asctime)s %(levelname)s %(message)s',
                # Adjusted path for the custom formatter
                '()': 'llm_gateway_core.utils.logging_setup.CustomJsonFormatter'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'json'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': 'logs/gateway.log', # Path relative to project root
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
