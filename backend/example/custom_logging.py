from __future__ import annotations

from datetime import datetime
import logging
import logging.handlers
import os
import sys

import structlog
from structlog.stdlib import ProcessorFormatter

from src.config import Settings
from src.models import AppMode

FILE_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s"
)


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure process-wide logging based on the configured app mode."""

    is_development = settings.APP_MODE is AppMode.DEVELOPMENT
    level = logging.DEBUG if is_development else logging.INFO

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    # --- File handler (unchanged) ---
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_filename = os.path.join(
        log_dir, f"app_log_{datetime.now().strftime('%Y%m%d')}.log"
    )
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_filename, when="midnight", interval=1, backupCount=0, encoding="utf-8"
    )
    file_handler.suffix = "%Y%m%d"
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt="[%X]"))
    root_logger.addHandler(file_handler)

    # --- structlog configuration ---
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if is_development:
        # Add module/lineno callsite info in development
        shared_processors.insert(
            1,
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
        )

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- Console handler: JSON via structlog ---
    console_formatter = ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Suppress overly verbose logs from third-party libraries
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)
    logging.getLogger("httpx").setLevel(level if is_development else logging.INFO)
    logging.getLogger("azure").setLevel(level)
    logging.getLogger("azure.core").setLevel(level)
    logging.getLogger("azure.identity").setLevel(level)
    logging.getLogger("azure.core.pipeline.transport").setLevel(level)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
        level
    )

    logger = logging.getLogger(settings.APP_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = True
    logger.debug("logging configured", extra={"app_mode": settings.APP_MODE.value})
    return logger