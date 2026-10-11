"""Greedy shortcut selection with overlap-aware corpus encoding."""

from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass
from heapq import merge
from pathlib import Path
from time import perf_counter
from typing import Callable, Sequence

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
    elapsed_seconds: float = 0.0
    selection_round_seconds: tuple[float, ...] = ()


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


def limit_optimizer_candidates(
    candidates: Sequence[Candidate], maximum: int
) -> list[Candidate]:
    """Deduplicate exact text, then keep the largest raw-potential savings scores."""
    if maximum < 1:
        raise ValueError("maximum candidates must be at least 1")
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        if not candidate.text:
            continue
        previous = unique.get(candidate.text)
        if previous is None or (candidate.score, candidate.frequency) > (
            previous.score,
            previous.frequency,
        ):
            unique[candidate.text] = candidate
    ranked = sorted(
        unique.values(),
        key=lambda candidate: (-candidate.score, -candidate.frequency, candidate.text),
    )
    return ranked[:maximum]


def _shortcut_events(text: str, shortcut: str, shortcut_cost: int) -> tuple[tuple[int, int, int], ...]:
    """Return (end, start, saved) events for every overlapping occurrence."""
    saved = len(shortcut) - shortcut_cost
    if saved <= 0:
        return ()
    events = []
    start = text.find(shortcut)
    while start != -1:
        events.append((start + len(shortcut), start, saved))
        start = text.find(shortcut, start + 1)
    return tuple(events)


def _maximum_non_overlapping_savings(
    text_length: int,
    event_streams: Sequence[Sequence[tuple[int, int, int]]],
) -> int:
    """Evaluate the same overlap-aware DP using only shortcut-ending positions."""
    best_positions = [0]
    best_savings = [0]
    current_end = None
    best_at_current_end = 0

    for end, start, saved in merge(*event_streams):
        if end != current_end:
            if current_end is not None:
                best_positions.append(current_end)
                best_savings.append(best_at_current_end)
            current_end = end
            best_at_current_end = best_savings[-1]

        start_index = bisect_right(best_positions, start) - 1
        best_at_current_end = max(
            best_at_current_end,
            best_savings[start_index] + saved,
        )

    if current_end is not None:
        best_positions.append(current_end)
        best_savings.append(best_at_current_end)
    return best_savings[-1]


def optimize_shortcuts(
    text: str,
    candidates: Sequence[Candidate],
    *,
    num_shortcuts: int = 20,
    shortcut_cost: int = 2,
    progress_callback: Callable[[str], None] | None = None,
) -> OptimizationResult:
    """Greedily select candidates using recomputed overlap-aware savings."""
    if num_shortcuts < 0:
        raise ValueError("num_shortcuts cannot be negative")
    if shortcut_cost < 0:
        raise ValueError("shortcut_cost cannot be negative")

    started_at = perf_counter()
    candidate_texts = sorted({candidate.text for candidate in candidates if candidate.text})
    candidate_events = {
        candidate_text: _shortcut_events(text, candidate_text, shortcut_cost)
        for candidate_text in candidate_texts
    }
    candidate_texts.sort(
        key=lambda item: (
            -len(candidate_events[item]) * (len(item) - shortcut_cost),
            item,
        )
    )
    selected: list[str] = []
    selected_rows: list[SelectedShortcut] = []
    round_timings = []
    current_cost = len(text)

    for round_number in range(1, num_shortcuts + 1):
        round_started_at = perf_counter()
        remaining_candidates = [item for item in candidate_texts if item not in selected]
        if progress_callback is not None:
            progress_callback(f"Selecting shortcut {round_number}/{num_shortcuts}...")
        best_text = None
        best_cost = current_cost
        selected_events = [candidate_events[item] for item in selected]
        progress_step = max(1, len(remaining_candidates) // 10)
        evaluated_count = 0
        for index, candidate_text in enumerate(remaining_candidates, start=1):
            event_count = len(candidate_events[candidate_text])
            maximum_additional_savings = event_count * (len(candidate_text) - shortcut_cost)
            best_additional_savings = current_cost - best_cost
            cannot_beat_best = maximum_additional_savings < best_additional_savings or (
                maximum_additional_savings == best_additional_savings
                and best_text is not None
                and candidate_text >= best_text
            )
            if not cannot_beat_best:
                evaluated_count += 1
                candidate_cost = len(text) - _maximum_non_overlapping_savings(
                    len(text), [*selected_events, candidate_events[candidate_text]]
                )
                if candidate_cost < best_cost or (
                    candidate_cost == best_cost
                    and best_text is not None
                    and candidate_text < best_text
                ):
                    best_text = candidate_text
                    best_cost = candidate_cost
            if progress_callback is not None and (
                index % progress_step == 0 or index == len(remaining_candidates)
            ):
                progress_callback(
                    f"  candidates evaluated: {evaluated_count}/{len(remaining_candidates)} "
                    f"(pruned: {index - evaluated_count})"
                )
        round_elapsed = perf_counter() - round_started_at
        round_timings.append(round_elapsed)
        if progress_callback is not None:
            progress_callback(f"  round elapsed: {round_elapsed:.3f}s")
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
        elapsed_seconds=perf_counter() - started_at,
        selection_round_seconds=tuple(round_timings),
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
        f"optimizer runtime: {result.elapsed_seconds:.3f}s",
        "selected shortcuts:",
    ]
    lines.extend(
        f"{item.selection_order}. {item.text!r} "
        f"(marginal saved: {item.marginal_keystrokes_saved})"
        for item in result.selected_shortcuts
    )
    return "\n".join(lines)