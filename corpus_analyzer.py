"""Find high-value word and substring shortcuts in text corpora."""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


WORD_PATTERN = re.compile(r"\b[\w]+(?:['-][\w]+)*\b", re.UNICODE)


@dataclass(frozen=True)
class Candidate:
    """A shortcut candidate and its estimated independent savings."""

    text: str
    frequency: int
    length: int
    raw_keystrokes_saved: int
    total_keystrokes_saved: int
    score: int

    def as_row(self) -> dict[str, int | str]:
        return {
            "substring": self.text,
            "frequency": self.frequency,
            "length": self.length,
            "raw_keystrokes_saved_per_use": self.raw_keystrokes_saved,
            "total_potential_keystrokes_saved": self.total_keystrokes_saved,
            "score": self.score,
        }


def read_corpus(path: str | Path) -> str:
    """Read one .txt file or concatenate all .txt files in a directory."""
    source = Path(path)
    if source.is_file():
        if source.suffix.lower() != ".txt":
            raise ValueError(f"Input file must have a .txt extension: {source}")
        return source.read_text(encoding="utf-8")
    if source.is_dir():
        files = sorted(
            item for item in source.iterdir() if item.is_file() and item.suffix.lower() == ".txt"
        )
        if not files:
            raise ValueError(f"Directory contains no .txt files: {source}")
        return "\n".join(item.read_text(encoding="utf-8") for item in files)
    raise FileNotFoundError(f"Input path does not exist: {source}")


def _candidates(
    counts: Counter[str],
    *,
    shortcut_cost: int,
    minimum_frequency: int,
    top_n: int,
) -> list[Candidate]:
    result = []
    for text, frequency in counts.items():
        length = len(text)
        raw_saved = length - shortcut_cost
        score = frequency * raw_saved
        if frequency < minimum_frequency or score <= 0:
            continue
        result.append(
            Candidate(
                text=text,
                frequency=frequency,
                length=length,
                raw_keystrokes_saved=raw_saved,
                total_keystrokes_saved=frequency * raw_saved,
                score=score,
            )
        )
    result.sort(key=lambda candidate: (-candidate.score, -candidate.frequency, candidate.text))
    return result[:top_n]


def _substring_counts(text: str, minimum_length: int, maximum_length: int) -> Counter[str]:
    counts: Counter[str] = Counter()
    for length in range(minimum_length, maximum_length + 1):
        for start in range(0, len(text) - length + 1):
            counts[text[start : start + length]] += 1
    return counts


def _word_counts(text: str) -> Counter[str]:
    return Counter(match.group(0).casefold() for match in WORD_PATTERN.finditer(text))


def analyze_text(
    text: str,
    *,
    minimum_frequency: int = 2,
    minimum_length: int = 2,
    maximum_length: int = 10,
    shortcut_cost: int = 2,
    top_n: int = 100,
) -> tuple[list[Candidate], list[Candidate]]:
    """Return (substring candidates, word candidates), each independently ranked."""
    if minimum_frequency < 1:
        raise ValueError("minimum_frequency must be at least 1")
    if minimum_length < 1 or maximum_length < minimum_length:
        raise ValueError("length bounds are invalid")
    if shortcut_cost < 0:
        raise ValueError("shortcut_cost cannot be negative")
    if top_n < 1:
        raise ValueError("top_n must be at least 1")

    substring_counts = _substring_counts(text, minimum_length, maximum_length)
    word_counts = _word_counts(text)
    return (
        _candidates(
            substring_counts,
            shortcut_cost=shortcut_cost,
            minimum_frequency=minimum_frequency,
            top_n=top_n,
        ),
        _candidates(
            word_counts,
            shortcut_cost=shortcut_cost,
            minimum_frequency=minimum_frequency,
            top_n=top_n,
        ),
    )


def analyze_path(path: str | Path, **kwargs: int) -> tuple[list[Candidate], list[Candidate]]:
    return analyze_text(read_corpus(path), **kwargs)


CSV_FIELDS = (
    "substring",
    "frequency",
    "length",
    "raw_keystrokes_saved_per_use",
    "total_potential_keystrokes_saved",
    "score",
    "candidate_type",
)


def write_csv(
    path: str | Path,
    substring_candidates: Sequence[Candidate],
    word_candidates: Sequence[Candidate],
) -> None:
    """Write both result tables to one CSV, marked by candidate_type."""
    with Path(path).open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for candidate_type, candidates in (
            ("substring", substring_candidates),
            ("word", word_candidates),
        ):
            for candidate in candidates:
                row = candidate.as_row()
                row["candidate_type"] = candidate_type
                writer.writerow(row)


def format_table(title: str, candidates: Iterable[Candidate]) -> str:
    lines = [title, "substring\tfrequency\tlength\traw_saved\ttotal_saved\tscore"]
    lines.extend(
        f"{candidate.text!r}\t{candidate.frequency}\t{candidate.length}\t"
        f"{candidate.raw_keystrokes_saved}\t{candidate.total_keystrokes_saved}\t{candidate.score}"
        for candidate in candidates
    )
    return "\n".join(lines)