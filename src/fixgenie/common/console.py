"""
Console helper with a graceful fallback.

Uses `rich` for pretty, colored tables when installed. If rich isn't available,
falls back to a plain-text console + table that strip markup and print normally,
so the CLI never crashes just because an optional pretty-printer is missing.
"""
from __future__ import annotations

import re

_MARKUP = re.compile(r"\[/?[a-zA-Z0-9 _#=]+\]")


def _strip(text: object) -> str:
    return _MARKUP.sub("", str(text))


class _PlainTable:
    """Minimal stand-in for rich.table.Table."""

    def __init__(self, title: str = "") -> None:
        self.title = title
        self._cols: list[str] = []
        self._rows: list[list[str]] = []

    def add_column(self, header: str, **_kwargs) -> None:
        self._cols.append(header)

    def add_row(self, *cells: object) -> None:
        self._rows.append([str(c) for c in cells])

    def render_plain(self) -> str:
        lines = []
        if self.title:
            lines.append(_strip(self.title))
        if self._cols:
            lines.append("  ".join(self._cols))
            lines.append("-" * (len("  ".join(self._cols))))
        for row in self._rows:
            lines.append("  ".join(row))
        return "\n".join(lines)


class _PlainConsole:
    """Minimal stand-in for rich.console.Console."""

    def print(self, *args, **_kwargs) -> None:
        for a in args:
            if isinstance(a, _PlainTable):
                print(a.render_plain())
            else:
                print(_strip(a))


try:
    from rich.console import Console as _RichConsole
    from rich.table import Table as _RichTable

    console = _RichConsole()

    def make_table(title: str = ""):
        return _RichTable(title=title)

except Exception:  # rich not installed
    console = _PlainConsole()

    def make_table(title: str = ""):
        return _PlainTable(title=title)
