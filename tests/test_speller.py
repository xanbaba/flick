"""Tests for backend.app.services.speller (ARCHITECTURE.md section 13)."""

from __future__ import annotations

from backend.app.services.speller import SYMBOLS, Speller, speller_arity


def test_arity_defaults_to_4_from_config_without_a_speller_block() -> None:
    assert speller_arity() == 4


def test_root_offers_at_most_n_labels() -> None:
    speller = Speller()
    options = speller.options()
    assert len(options) == 4
    assert all(option.symbol is None for option in options)


def test_walk_reaches_a_single_letter_and_speak() -> None:
    speller = Speller()
    # Last root group ends in SPEAK. Descend until a leaf.
    path: tuple[int, ...] = (3,)
    options = speller.options(path)
    speak = next(option for option in options if option.symbol == "SPEAK")
    assert speak.label == "SPEAK"

    letter_path: tuple[int, ...] = ()
    seen: list[str] = []
    for _ in range(6):
        options = speller.options(letter_path)
        if options[0].symbol is not None:
            seen.append(options[0].symbol)
            break
        letter_path = speller.descend(letter_path, 0)
    assert seen and seen[0] in SYMBOLS
    assert len(seen[0]) == 1
