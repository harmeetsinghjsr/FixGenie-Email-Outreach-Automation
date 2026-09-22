"""
Shared logging configuration.

Uses `rich` for readable, colored console output when it's installed, and falls
back to plain stdlib logging if it isn't — so the system never crashes on import
just because an optional pretty-printing dependency is missing.
"""
from __future__ import annotations

import logging

_CONFIGURED = False


def _handler() -> logging.Handler:
    """Prefer a RichHandler; degrade to a plain StreamHandler if rich is absent."""
    try:
        from rich.logging import RichHandler

        return RichHandler(rich_tracebacks=True, show_path=False)
    except Exception:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%X"))
        return handler


def get_logger(name: str) -> logging.Logger:
    """Return a module logger, configuring the root handler once."""
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(level=logging.INFO, format="%(message)s",
                            datefmt="[%X]", handlers=[_handler()])
        # Quiet down noisy third-party libraries.
        for noisy in ("urllib3", "gspread", "google", "playwright"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _CONFIGURED = True
    return logging.getLogger(name)
