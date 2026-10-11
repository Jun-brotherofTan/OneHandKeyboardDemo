"""Corpus loading and alphabet bigram counting for mirror-layout optimization."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from corpus_files import list_corpus_files


def read_corpus(path: str | Path) -> str:
    """Read one UTF-8 .txt file or all .txt and .py files in a directory."""
    source = Path(path)
    if source.is_file():
        if source.suffix.lower() != ".txt":
            raise ValueError(f"Input file must have a .txt extension: {source}")
        return source.read_text(encoding="utf-8")
    if source.is_dir():
        files = list_corpus_files(
            source, include_nested_txt=True, case_sensitive_txt=True
        )
        if not files:
            raise ValueError(f"Directory contains no .txt or .py files: {source}")
        return "\n".join(item.read_text(encoding="utf-8") for item in files)
    raise FileNotFoundError(f"Input path does not exist: {source}")


def normalize_letters(text: str) -> str:
    """Keep only ASCII letters and normalize them to lowercase."""
    return "".join(character for character in text.lower() if "a" <= character <= "z")


def count_bigrams(text: str) -> Counter[tuple[str, str]]:
    """Count adjacent alphabetic transitions after filtering non-letters."""
    letters = normalize_letters(text)
    return Counter(zip(letters, letters[1:]))


def count_unigrams(text: str) -> Counter[str]:
    """Count normalized ASCII letters for per-key usage metrics."""
    return Counter(normalize_letters(text))
