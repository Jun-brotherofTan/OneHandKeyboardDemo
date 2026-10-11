"""Find high-value word and substring shortcuts in text corpora."""

from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from corpus_files import list_corpus_files


WORD_PATTERN = re.compile(r"\b[\w]+(?:['-][\w]+)*\b", re.UNICODE)
LICENSE_HEADER_PATTERN = re.compile(
    r"SPDX-License-Identifier|Copyright|Licensed under the|Apache License|MIT License|"
    r"GNU Affero General Public License|GNU General Public License",
    re.IGNORECASE,
)
PYTHON_ENCODING_PATTERN = re.compile(r"coding[:=]\s*[-\w.]+", re.IGNORECASE)
MAX_HEADER_LINES = 80


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


def clean_python_license_header(text: str) -> str:
    """Remove likely license comment blocks before the first Python code line."""
    lines = text.splitlines(keepends=True)
    header_end = 0
    for line in lines[:MAX_HEADER_LINES]:
        stripped = line.lstrip("\ufeff").lstrip()
        if not stripped or stripped.startswith("#"):
            header_end += 1
            continue
        break

    header_comments = [
        line for line in lines[:header_end] if line.lstrip("\ufeff").lstrip().startswith("#")
    ]
    if not LICENSE_HEADER_PATTERN.search("".join(header_comments)):
        return text

    preamble = []
    for line in lines[:header_end]:
        stripped = line.lstrip("\ufeff").lstrip()
        if stripped.startswith("#!") or PYTHON_ENCODING_PATTERN.search(stripped):
            preamble.append(line)
    return "".join([*preamble, *lines[header_end:]])


def read_corpus(path: str | Path, *, keep_license_headers: bool = False) -> str:
    """Read .txt and .py files, cleaning likely license comments in Python headers."""
    source = Path(path)

    def read_file(item: Path) -> str:
        contents = item.read_text(encoding="utf-8")
        if item.suffix.lower() == ".py" and not keep_license_headers:
            return clean_python_license_header(contents)
        return contents

    if source.is_file():
        if source.suffix.lower() not in {".txt", ".py"}:
            raise ValueError(f"Input file must have a .txt or .py extension: {source}")
        return read_file(source)
    if source.is_dir():
        files = list_corpus_files(
            source, include_nested_txt=False, case_sensitive_txt=False
        )
        if not files:
            raise ValueError(f"Directory contains no .txt or .py files: {source}")
        return "\n".join(read_file(item) for item in files)
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
    ascii_letters = [0] * (len(text) + 1)
    forbidden_controls = [0] * (len(text) + 1)
    for index, character in enumerate(text):
        ascii_letters[index + 1] = ascii_letters[index] + int(
            "a" <= character <= "z" or "A" <= character <= "Z"
        )
        forbidden_controls[index + 1] = forbidden_controls[index] + int(
            character in "\n\r\t"
        )

    for length in range(minimum_length, maximum_length + 1):
        for start in range(0, len(text) - length + 1):
            end = start + length
            if text[start].isspace():
                continue
            if ascii_letters[end] == ascii_letters[start]:
                continue
            if forbidden_controls[end] != forbidden_controls[start]:
                continue
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


def analyze_path(
    path: str | Path, **kwargs: int | bool
) -> tuple[list[Candidate], list[Candidate]]:
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