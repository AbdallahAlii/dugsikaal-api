import logging.config
import os
from typing import Dict, Any

def configure_logging(level: str) -> None:
    """Configures the logging for the Flask application."""
    log_level = level.upper()

    # Define the logging configuration dictionary
    LOGGING_CONFIG: Dict[str, Any] = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
            'json': {
                '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
                'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'standard',
            },
            # Optionally, you can add a file handler for persistent logs
            'file': {
                'class': 'logging.FileHandler',
                'filename': os.path.join(os.getcwd(), 'app.log'),
                'formatter': 'standard',
                'level': log_level,
            },
        },
        'loggers': {
            '': {  # Root logger
                'handlers': ['console'],
                'level': log_level,
                'propagate': True,
            },
            'werkzeug': {
                'handlers': ['console'],
                'level': 'INFO',  # Keep Werkzeug at INFO to avoid excessive debug noise
                'propagate': False,
            },
            'redis': {
                'handlers': ['console'],
                'level': log_level,
                'propagate': False,
            },
            # Add specific module loggers for targeted logging
            'app.auth.service.auth_service': {
                'handlers': ['console'],
                'level': log_level,
                'propagate': False,
            },
            'app.common.cache.cache_invalidator': {
                'handlers': ['console'],
                'level': log_level,
                'propagate': False,
            },
        }
    }

    # Apply the logging configuration
    logging.config.dictConfig(LOGGING_CONFIG)

    # Set up a logger for this module
    log = logging.getLogger(__name__)
    log.info(f"Logging configured with level: {log_level}")
