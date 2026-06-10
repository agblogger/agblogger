"""Tests for text utility functions."""

from __future__ import annotations

import string

import pytest
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


@pytest.mark.parametrize(
    "fenced_code",
    [
        "~~~\nsome code tokens here\n~~~",
        "````\nsome ``` code tokens here\n````",
        "```\nsome code tokens here\n````",
    ],
)
def test_supported_fenced_code_blocks_excluded(fenced_code: str) -> None:
    body = f"Before code.\n{fenced_code}\nAfter code."
    assert count_words(body) == 4


def test_multi_backtick_inline_code_excluded() -> None:
    body = "Use ``foo ` bar`` to assign"
    assert count_words(body) == 3


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


@given(
    st.sampled_from(["`", "~"]),
    st.integers(min_value=3, max_value=10),
    st.integers(min_value=0, max_value=5),
    st.text(alphabet=string.ascii_letters + string.digits + " \n", min_size=0, max_size=200),
)
@settings(max_examples=200)
def test_variable_length_fenced_code_excluded_property(
    marker: str,
    opening_length: int,
    closing_extension: int,
    code: str,
) -> None:
    opening = marker * opening_length
    closing = marker * (opening_length + closing_extension)
    body = f"Before prose\n{opening}\n{code}\n{closing}\nAfter prose"
    assert count_words(body) == 4


@given(
    st.integers(min_value=1, max_value=10),
    st.text(alphabet=string.ascii_letters + string.digits + " \n~", min_size=1, max_size=200),
)
@settings(max_examples=200)
def test_variable_length_inline_code_excluded_property(delimiter_length: int, code: str) -> None:
    delimiter = "`" * delimiter_length
    body = f"Before prose {delimiter}{code}{delimiter} after prose"
    assert count_words(body) == 4
