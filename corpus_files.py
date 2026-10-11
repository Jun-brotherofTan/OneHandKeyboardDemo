"""Collect text corpus files while skipping generated and hidden directories."""

from __future__ import annotations

import os
from pathlib import Path


IGNORED_DIRECTORY_NAMES = frozenset(
    {".git", ".venv", "venv", "__pycache__", "site-packages", "node_modules", "build", "dist"}
)


def list_corpus_files(
    source: Path,
    *,
    include_nested_txt: bool,
    case_sensitive_txt: bool,
) -> list[Path]:
    """Return supported files, always searching for Python files recursively."""
    files = []
    for directory, subdirectories, filenames in os.walk(source):
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if not name.startswith(".") and name not in IGNORED_DIRECTORY_NAMES
        )
        current = Path(directory)
        for filename in filenames:
            path = current / filename
            suffix = path.suffix if case_sensitive_txt else path.suffix.lower()
            if suffix == ".py" or (
                suffix == ".txt" and (include_nested_txt or current == source)
            ):
                files.append(path)
    return sorted(files)