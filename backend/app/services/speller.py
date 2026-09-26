"""N-ary speller tree (ARCHITECTURE.md section 13).

Speller mode walks an N-ary search over the alphabet. N is read from
``config.yaml`` under ``speller.n`` when that block exists. The frozen
config shipped with this repository has no ``speller`` block, so the
section 13 default of 4 applies. Each step presents up to N labels.
A label that still covers several symbols descends; a label that is a
single symbol commits it. ``SPEAK`` is a leaf that ends the loop.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

SYMBOLS: tuple[str, ...] = tuple("abcdefghijklmnopqrstuvwxyz") + (" ", "DEL", "SPEAK")

_DISPLAY = {" ": "space", "DEL": "delete", "SPEAK": "SPEAK"}


class SpellerOption(BaseModel):
    label: str
    symbol: str | None  # set when choosing this option commits a symbol


def speller_arity(config_path: Path | str = "config.yaml") -> int:
    """N from config, default 4 (section 13)."""
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    block = raw.get("speller") or {}
    try:
        n = int(block.get("n", 4))
    except (TypeError, ValueError):
        return 4
    return n if n >= 2 else 4


def _display(symbol: str) -> str:
    return _DISPLAY.get(symbol, symbol)


def _split(items: list[str], n: int) -> list[list[str]]:
    """Contiguous groups, at most ``n``, sizes differ by at most one."""
    if len(items) <= n:
        return [[item] for item in items]
    base, extra = divmod(len(items), n)
    groups: list[list[str]] = []
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        if size <= 0:
            break
        groups.append(items[start : start + size])
        start += size
    return groups


def _group_label(group: list[str]) -> str:
    if len(group) == 1:
        return _display(group[0])
    if all(len(symbol) == 1 and symbol.isalpha() for symbol in group):
        return f"{group[0]}-{group[-1]}"
    return f"{_display(group[0])}-{_display(group[-1])}"


class Speller:
    def __init__(self, n: int | None = None, config_path: Path | str = "config.yaml") -> None:
        self.n = n if n is not None else speller_arity(config_path)
        self._symbols = list(SYMBOLS)

    def options(self, path: tuple[int, ...] = ()) -> list[SpellerOption]:
        group = self._descend(path)
        parts = _split(group, self.n)
        options: list[SpellerOption] = []
        for part in parts:
            if len(part) == 1:
                options.append(SpellerOption(label=_display(part[0]), symbol=part[0]))
            else:
                options.append(SpellerOption(label=_group_label(part), symbol=None))
        return options

    def descend(self, path: tuple[int, ...], index: int) -> tuple[int, ...]:
        """Append ``index`` when that option is a group, else return ``path``."""
        options = self.options(path)
        if index < 0 or index >= len(options):
            raise IndexError(index)
        if options[index].symbol is not None:
            return path
        return (*path, index)

    def commit(self, path: tuple[int, ...], index: int) -> str | None:
        """The symbol this option commits, or None if it only descends."""
        options = self.options(path)
        if index < 0 or index >= len(options):
            raise IndexError(index)
        return options[index].symbol

    def _descend(self, path: tuple[int, ...]) -> list[str]:
        group = self._symbols
        for index in path:
            parts = _split(group, self.n)
            if index < 0 or index >= len(parts):
                raise IndexError(index)
            group = parts[index]
        return group
