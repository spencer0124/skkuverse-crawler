from __future__ import annotations

import logging

import structlog

from .config import get_config


def configure_logging() -> None:
    cfg = get_config()

    level = logging.CRITICAL if cfg.is_test else logging.INFO

    structlog.reset_defaults()

    renderer: structlog.types.Processor
    if cfg.log_format == "dev":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if not cfg.is_test:
        logger = structlog.get_logger("config")
        logger.info("crawler_mode", mode=cfg.mode_label)


def get_logger(name: str = "", **initial_context: object) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name, **initial_context)
