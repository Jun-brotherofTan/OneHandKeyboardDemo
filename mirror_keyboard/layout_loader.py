"""Profile loading for the keyboard test overlay."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from layout import KEYS, Layout


@dataclass(frozen=True)
class KeyboardProfile:
    name: str
    path: Path
    normal_mapping: Mapping[str, str]
    mirror_mapping: Mapping[str, str]
    shortcut_mapping: Mapping[str, str]
    shortcut_profile_name: str


def load_layout_profile(
    layout_path: str | Path,
    shortcut_path: str | Path | None = None,
) -> KeyboardProfile:
    path = Path(layout_path)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required_fields = {"physical_key", "mirror_character"}
        if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
            raise ValueError(
                "Layout CSV must contain physical_key and mirror_character columns."
            )
        mapping = {}
        for row in reader:
            key = row["physical_key"].strip().lower()
            output = row["mirror_character"]
            if key in mapping:
                raise ValueError(f"Duplicate physical key in layout: {key}")
            mapping[key] = output
    layout = Layout(mapping)

    shortcut_mapping = {}
    shortcut_name = "not loaded"
    if shortcut_path is not None:
        shortcut_file = Path(shortcut_path)
        with shortcut_file.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or "physical_key" not in reader.fieldnames:
                raise ValueError("Shortcut CSV must contain a physical_key column.")
            value_field = next(
                (name for name in ("shortcut", "output") if name in reader.fieldnames),
                None,
            )
            if value_field is None:
                raise ValueError("Shortcut CSV must contain a shortcut or output column.")
            for row in reader:
                key = row["physical_key"].strip().lower()
                if key not in layout.mirror_by_physical:
                    raise ValueError(f"Shortcut profile contains an inactive key: {key}")
                if key in shortcut_mapping:
                    raise ValueError(f"Duplicate physical key in shortcut profile: {key}")
                shortcut_mapping[key] = row[value_field]
        shortcut_name = shortcut_file.name

    normal_mapping = {key.normal: key.normal for key in KEYS}
    return KeyboardProfile(
        name=path.name,
        path=path.resolve(),
        normal_mapping=MappingProxyType(normal_mapping),
        mirror_mapping=MappingProxyType(dict(layout.mirror_by_physical)),
        shortcut_mapping=MappingProxyType(shortcut_mapping),
        shortcut_profile_name=shortcut_name,
    )


def standard_profile_paths(layout_path: str | Path) -> dict[str, Path]:
    directory = Path(layout_path).resolve().parent
    return {str(index): directory / f"layout_{letter}.csv" for index, letter in enumerate("ABCDE", 1)}