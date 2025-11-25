# import logging
# import logging.config
# import os
# from typing import Dict, Any
#
# def configure_logging(level: str) -> None:
#     """Configures the logging for the Flask application."""
#     log_level = level.upper()
#
#     # Use a central logs directory (bench-style)
#     LOG_DIR = os.getenv("LOG_DIR", "/srv/pms-bench/logs")
#     os.makedirs(LOG_DIR, exist_ok=True)
#
#     LOGGING_CONFIG: Dict[str, Any] = {
#         'version': 1,
#         'disable_existing_loggers': False,
#         'formatters': {
#             'standard': {
#                 'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]',
#                 'datefmt': '%Y-%m-%d %H:%M:%S',
#             },
#             'json': {
#                 '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
#                 'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
#             },
#         },
#         'handlers': {
#             'console': {
#                 'class': 'logging.StreamHandler',
#                 'formatter': 'standard',
#             },
#             'file': {
#                 'class': 'logging.FileHandler',
#                 'filename': os.path.join(LOG_DIR, 'app.log'),
#                 'formatter': 'standard',
#                 'level': log_level,
#             },
#         },
#         'loggers': {
#             # Root logger: send to console AND file
#             '': {
#                 'handlers': ['console', 'file'],
#                 'level': log_level,
#                 'propagate': False,
#             },
#             'werkzeug': {
#                 'handlers': ['console'],
#                 'level': 'INFO',
#                 'propagate': False,
#             },
#             'redis': {
#                 'handlers': ['console'],
#                 'level': log_level,
#                 'propagate': False,
#             },
#             'app.auth.service.auth_service': {
#                 'handlers': ['console', 'file'],
#                 'level': log_level,
#                 'propagate': False,
#             },
#             'app.common.cache.cache_invalidator': {
#                 'handlers': ['console', 'file'],
#                 'level': log_level,
#                 'propagate': False,
#             },
#         }
#     }
#
#     logging.config.dictConfig(LOGGING_CONFIG)
#     log = logging.getLogger(__name__)
#     log.info(f"Logging configured with level: {log_level}, LOG_DIR={LOG_DIR}")
import logging
import logging.config
import os
from typing import Dict, Any


def configure_logging(level: str) -> None:
    """Configures the logging for the Flask application."""
    log_level = level.upper()

    # ------------------------------------------------------------------
    # Windows-safe: ensure stdout/stderr use UTF-8 so emojis won't crash
    # ------------------------------------------------------------------
    try:
        import sys

        # Only available on TextIOWrapper (Python 3.7+)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # Best-effort only; never break app because of logging config
        pass

    # Use a central logs directory (bench-style)
    LOG_DIR = os.getenv("LOG_DIR", "/srv/pms-bench/logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    LOGGING_CONFIG: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                # Optional: explicitly choose stdout instead of stderr
                # "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.FileHandler",
                "filename": os.path.join(LOG_DIR, "app.log"),
                "formatter": "standard",
                "level": log_level,
                # Make sure log file is UTF-8 as well
                "encoding": "utf-8",
            },
        },
        "loggers": {
            # Root logger: send to console AND file
            "": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "werkzeug": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "redis": {
                "handlers": ["console"],
                "level": log_level,
                "propagate": False,
            },
            "app.auth.service.auth_service": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "app.common.cache.cache_invalidator": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(LOGGING_CONFIG)
    log = logging.getLogger(__name__)
    log.info(f"Logging configured with level: {log_level}, LOG_DIR={LOG_DIR}")
