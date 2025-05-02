import os
from logging.config import dictConfig

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

