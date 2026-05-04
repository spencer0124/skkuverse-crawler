"""Branch coverage for the 3-state dispatch ping boot log.

The `_log_dispatch_state` helper is what makes a deploy-time misconfig
(exactly one of DISPATCH_URL / INTERNAL_DISPATCH_TOKEN set) detectable
in normal log reading. The matrix is small enough to enumerate.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from skkuverse_crawler.shared.logger import _log_dispatch_state


def _cfg(url, tok):
    return SimpleNamespace(dispatch_url=url, internal_dispatch_token=tok)


class TestLogDispatchState:
    def test_both_set_logs_info_with_host(self):
        logger = MagicMock()
        _log_dispatch_state(logger, _cfg("http://api-1:3000/internal/notices/dispatch-pending", "SECRET-XYZ-9999"))
        logger.info.assert_called_once()
        args, kwargs = logger.info.call_args
        assert args[0] == "dispatch_ping_enabled"
        assert kwargs["url_host"] == "api-1:3000"
        # Token value MUST NOT appear anywhere in the call
        assert "SECRET-XYZ-9999" not in str(kwargs)
        logger.error.assert_not_called()
        logger.warning.assert_not_called()

    def test_both_unset_logs_warning(self):
        logger = MagicMock()
        _log_dispatch_state(logger, _cfg(None, None))
        logger.warning.assert_called_once()
        args, _kwargs = logger.warning.call_args
        assert args[0] == "dispatch_ping_disabled"
        logger.info.assert_not_called()
        logger.error.assert_not_called()

    def test_only_url_set_logs_error(self):
        logger = MagicMock()
        _log_dispatch_state(logger, _cfg("http://api-1:3000/x", None))
        logger.error.assert_called_once()
        args, kwargs = logger.error.call_args
        assert args[0] == "dispatch_ping_misconfigured"
        assert kwargs["dispatch_url_set"] is True
        assert kwargs["token_set"] is False

    def test_only_token_set_logs_error(self):
        logger = MagicMock()
        _log_dispatch_state(logger, _cfg(None, "SECRET-XYZ-9999"))
        logger.error.assert_called_once()
        args, kwargs = logger.error.call_args
        assert args[0] == "dispatch_ping_misconfigured"
        assert kwargs["dispatch_url_set"] is False
        assert kwargs["token_set"] is True
        # Token value MUST NOT appear in any log args
        assert "SECRET-XYZ-9999" not in str(args) and "SECRET-XYZ-9999" not in str(kwargs)
