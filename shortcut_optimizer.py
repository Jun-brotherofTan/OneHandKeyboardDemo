"""Greedy shortcut selection with overlap-aware corpus encoding."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from corpus_analyzer import Candidate


@dataclass(frozen=True)
class SelectedShortcut:
    text: str
    selection_order: int
    marginal_keystrokes_saved: int
    cumulative_keystrokes_saved: int


@dataclass(frozen=True)
class OptimizationResult:
    original_character_count: int
    original_keystroke_count: int
    optimized_keystroke_count: int
    total_keystrokes_saved: int
    percentage_saved: float
    selected_shortcuts: tuple[SelectedShortcut, ...]


def encoded_keystrokes(text: str, shortcuts: Sequence[str], shortcut_cost: int) -> int:
    """Return the minimum keystrokes for text using the supplied shortcuts."""
    costs = [0] * (len(text) + 1)
    for position in range(len(text) - 1, -1, -1):
        best = 1 + costs[position + 1]
        for shortcut in shortcuts:
            if text.startswith(shortcut, position):
                best = min(best, shortcut_cost + costs[position + len(shortcut)])
        costs[position] = best
    return costs[0]


def optimize_shortcuts(
    text: str,
    candidates: Sequence[Candidate],
    *,
    num_shortcuts: int = 20,
    shortcut_cost: int = 2,
) -> OptimizationResult:
    """Greedily select candidates using recomputed overlap-aware savings."""
    if num_shortcuts < 0:
        raise ValueError("num_shortcuts cannot be negative")
    if shortcut_cost < 0:
        raise ValueError("shortcut_cost cannot be negative")

    candidate_texts = sorted({candidate.text for candidate in candidates if candidate.text})
    selected: list[str] = []
    selected_rows: list[SelectedShortcut] = []
    current_cost = len(text)

    for _ in range(num_shortcuts):
        best_text = None
        best_cost = current_cost
        for candidate_text in candidate_texts:
            if candidate_text in selected:
                continue
            candidate_cost = encoded_keystrokes(text, [*selected, candidate_text], shortcut_cost)
            if candidate_cost < best_cost or (
                candidate_cost == best_cost and best_text is not None and candidate_text < best_text
            ):
                best_text = candidate_text
                best_cost = candidate_cost
        if best_text is None or best_cost >= current_cost:
            break
        selected.append(best_text)
        marginal_savings = current_cost - best_cost
        selected_rows.append(
            SelectedShortcut(
                text=best_text,
                selection_order=len(selected),
                marginal_keystrokes_saved=marginal_savings,
                cumulative_keystrokes_saved=len(text) - best_cost,
            )
        )
        current_cost = best_cost

    original_count = len(text)
    total_saved = original_count - current_cost
    percentage_saved = (100 * total_saved / original_count) if original_count else 0.0
    return OptimizationResult(
        original_character_count=original_count,
        original_keystroke_count=original_count,
        optimized_keystroke_count=current_cost,
        total_keystrokes_saved=total_saved,
        percentage_saved=percentage_saved,
        selected_shortcuts=tuple(selected_rows),
    )


SELECTED_CSV_FIELDS = (
    "selection_order",
    "shortcut",
    "marginal_keystrokes_saved",
    "cumulative_keystrokes_saved",
)


def write_selected_csv(path: str | Path, result: OptimizationResult) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=SELECTED_CSV_FIELDS)
        writer.writeheader()
        for shortcut in result.selected_shortcuts:
            writer.writerow(
                {
                    "selection_order": shortcut.selection_order,
                    "shortcut": shortcut.text,
                    "marginal_keystrokes_saved": shortcut.marginal_keystrokes_saved,
                    "cumulative_keystrokes_saved": shortcut.cumulative_keystrokes_saved,
                }
            )


def format_optimization(result: OptimizationResult) -> str:
    lines = [
        "OPTIMIZATION SUMMARY",
        f"original characters: {result.original_character_count}",
        f"original keystrokes: {result.original_keystroke_count}",
        f"optimized keystrokes: {result.optimized_keystroke_count}",
        f"total keystrokes saved: {result.total_keystrokes_saved}",
        f"percentage saved: {result.percentage_saved:.2f}%",
        "selected shortcuts:",
    ]
    lines.extend(
        f"{item.selection_order}. {item.text!r} "
        f"(marginal saved: {item.marginal_keystrokes_saved})"
        for item in result.selected_shortcuts
    )
    return "\n".join(lines)