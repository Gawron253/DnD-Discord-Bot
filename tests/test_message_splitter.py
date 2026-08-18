"""Unit tests for Smart Paragraph Splitter (ai/message_splitter.py)."""
import pytest
from ai.message_splitter import split_long_message


def test_splitter_short_text():
    text = "Krótki tekst"
    chunks = split_long_message(text, limit=1900)
    assert chunks == [text]


def test_splitter_multiple_paragraphs():
    p1 = "Pierwszy akapit tekstu." * 30
    p2 = "Drugi akapit tekstu." * 30
    combined = f"{p1}\n\n{p2}"
    chunks = split_long_message(combined, limit=400)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 400
        assert c.strip() == c


def test_splitter_empty_text():
    assert split_long_message("") == []
    assert split_long_message("   ") == []
    assert split_long_message("\n\n\t  ") == []


def test_splitter_single_giant_sentence():
    giant = "A" * 1500
    chunks = split_long_message(giant, limit=500)
    assert len(chunks) == 3
    for c in chunks:
        assert len(c) <= 500


def test_splitter_preserves_sentence_boundaries():
    s1 = "To jest pierwsze zdanie o wielkim smoku."
    s2 = "To jest drugie zdanie o dzielnym rycerzu."
    s3 = "To jest trzecie zdanie o skarbie w podziemiach."
    text = f"{s1} {s2} {s3}"
    chunks = split_long_message(text, limit=50)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 50


def test_splitter_polish_diacritics_and_punctuation():
    text = "Zażółć gęślą jaźń! Czy widzisz ten loch? Tak, jest ciemno... Ruszajmy!"
    chunks = split_long_message(text, limit=35)
    assert len(chunks) >= 2
    rejoined = " ".join(chunks)
    assert "Zażółć gęślą jaźń" in rejoined
    assert "Ruszajmy!" in rejoined


def test_splitter_boundary_exact_limit():
    exact_text = "X" * 1900
    chunks = split_long_message(exact_text, limit=1900)
    assert len(chunks) == 1
    assert chunks[0] == exact_text

    over_limit = "X" * 1901
    chunks_over = split_long_message(over_limit, limit=1900)
    assert len(chunks_over) == 2
    assert len(chunks_over[0]) <= 1900
    assert len(chunks_over[1]) <= 1900
