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
    os.makedirs('logs', exist_ok=True)
    
    dictConfig({
        'version': 1,
        'formatters': {
            'json': {
                'fmt': '%(asctime)s %(levelname)s %(message)s',
                '()': 'log_config.CustomJsonFormatter'
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

