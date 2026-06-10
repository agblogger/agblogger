"""Tests for text utility functions."""

from __future__ import annotations

import string

from hypothesis import given, settings
from hypothesis import strategies as st

from backend.utils.text import count_words

_WORD = st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=15)
_PROSE = st.lists(_WORD, min_size=0, max_size=100)


def test_empty_string_returns_zero() -> None:
    assert count_words("") == 0


def test_plain_prose() -> None:
    assert count_words("Hello world this is a post") == 6


def test_fenced_code_block_excluded() -> None:
    body = "Before code.\n```\nsome code tokens here\n```\nAfter code."
    assert count_words(body) == 4  # "Before", "code.", "After", "code."


def test_inline_code_excluded() -> None:
    body = "Use `foo = 1` to assign"
    # strip "`foo = 1`" → "Use  to assign" → 3 words
    assert count_words(body) == 3


def test_multiple_fenced_blocks_excluded() -> None:
    body = "First.\n```\ncode1\n```\nMiddle.\n```\ncode2\n```\nLast."
    assert count_words(body) == 3  # "First.", "Middle.", "Last."


@given(_PROSE)
@settings(max_examples=200)
def test_plain_prose_word_count_property(words: list[str]) -> None:
    body = " ".join(words)
    assert count_words(body) == len(words)


@given(
    st.text(alphabet=string.ascii_letters + " \n", min_size=0, max_size=200),
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=50),
)
@settings(max_examples=200)
def test_fenced_code_excluded_property(prose: str, code: str) -> None:
    body = f"{prose}\n```\n{code}\n```\n"
    prose_count = len(prose.split())
    assert count_words(body) == prose_count
