from __future__ import annotations

import logging
from urllib.parse import urlparse

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
        _log_dispatch_state(logger, cfg)
        _log_discord_state(logger, cfg)


def _log_dispatch_state(logger: structlog.stdlib.BoundLogger, cfg: object) -> None:
    """3-state boot log for the FCM dispatch ping config.

    - both set     → INFO  dispatch_ping_enabled       (normal run)
    - both unset   → WARN  dispatch_ping_disabled      (intentional disable)
    - exactly one  → ERROR dispatch_ping_misconfigured (deploy mistake — silent
                                                        failure mode otherwise)

    Token value is NEVER logged; only its presence as a boolean flag.
    """
    url = getattr(cfg, "dispatch_url", None)
    tok = getattr(cfg, "internal_dispatch_token", None)
    url_set = bool(url)
    tok_set = bool(tok)
    if url_set and tok_set:
        logger.info("dispatch_ping_enabled", url_host=urlparse(url).netloc)
    elif url_set or tok_set:
        logger.error(
            "dispatch_ping_misconfigured",
            reason=(
                "exactly one of DISPATCH_URL / INTERNAL_DISPATCH_TOKEN is set; "
                "both must be set together to enable the ping"
            ),
            dispatch_url_set=url_set,
            token_set=tok_set,
        )
    else:
        logger.warning(
            "dispatch_ping_disabled",
            reason="DISPATCH_URL and INTERNAL_DISPATCH_TOKEN both unset",
        )


def _log_discord_state(logger: structlog.stdlib.BoundLogger, cfg: object) -> None:
    """2-state boot log for crawl-health Discord alerts (single env var, so no
    misconfigured state exists — unlike the dispatch ping pair).

    Webhook URL embeds a secret token; only the host is ever logged.
    """
    url = getattr(cfg, "discord_webhook_url", None)
    if url:
        logger.info("discord_alerts_enabled", url_host=urlparse(url).netloc)
    else:
        logger.warning(
            "discord_alerts_disabled",
            reason="DISCORD_WEBHOOK_URL unset — source-down alerts will be skipped",
        )


def get_logger(name: str = "", **initial_context: object) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name, **initial_context)
