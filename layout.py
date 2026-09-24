"""Physical key, finger, and mirrored-layer representations."""

from __future__ import annotations

from dataclasses import dataclass

ROWS = ("QWERT", "ASDFG", "ZXCVB")
FINGERS = (
    ("left_pinky", "left_ring", "left_middle", "left_index", "left_index"),
    ("left_pinky", "left_ring", "left_middle", "left_index", "left_index"),
    ("left_pinky", "left_ring", "left_middle", "left_index", "left_index"),
)
NORMAL_LETTERS = frozenset("qwertasdfgzxcvb")
MIRROR_LETTERS = frozenset("hijklmnopuy")
MIRROR_SLOTS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11)
FIXED_PUNCTUATION = {9: ";", 12: ",", 13: ".", 14: "/"}


@dataclass(frozen=True)
class PhysicalKey:
    row: int
    column: int
    normal: str
    finger: str

    @property
    def physical_key(self) -> str:
        return self.normal


KEYS = tuple(
    PhysicalKey(row, column, normal.lower(), FINGERS[row][column])
    for row, letters in enumerate(ROWS)
    for column, normal in enumerate(letters)
)
NORMAL_TO_FINGER = {key.normal: key.finger for key in KEYS}


class Layout:
    """A fixed normal layer paired with a permuted alphabet mirror layer."""

    def __init__(self, mirror_by_physical: dict[str, str]):
        expected_keys = {key.normal for key in KEYS}
        if set(mirror_by_physical) != expected_keys:
            raise ValueError("mirror mapping must contain every physical key exactly once")
        letters = [mirror_by_physical[key.normal] for index, key in enumerate(KEYS) if index in MIRROR_SLOTS]
        punctuation = {index: mirror_by_physical[KEYS[index].normal] for index in FIXED_PUNCTUATION}
        if set(letters) != MIRROR_LETTERS or len(letters) != len(MIRROR_LETTERS) or punctuation != FIXED_PUNCTUATION:
            raise ValueError("mirror mapping must contain exactly the 11 mirror letters")
        self.mirror_by_physical = dict(mirror_by_physical)

    @classmethod
    def from_letters(cls, letters: tuple[str, ...] | list[str]) -> "Layout":
        if len(letters) != len(MIRROR_LETTERS):
            raise ValueError("there must be exactly 11 mirror letters")
        mapping = {key.normal: FIXED_PUNCTUATION.get(index, "") for index, key in enumerate(KEYS)}
        for index, letter in zip(MIRROR_SLOTS, letters):
            mapping[KEYS[index].normal] = letter
        return cls(mapping)

    def finger_for(self, letter: str) -> str:
        return self.key_for(letter).finger

    def key_for(self, letter: str) -> PhysicalKey:
        character = letter.lower()
        if character in NORMAL_TO_FINGER:
            return next(key for key in KEYS if key.normal == character)
        for key in KEYS:
            if self.mirror_by_physical[key.normal] == character:
                return key
        raise ValueError(f"unsupported alphabet letter: {letter}")

    def row_for(self, letter: str) -> int:
        return self.key_for(letter).row

    def column_for(self, letter: str) -> int:
        return self.key_for(letter).column

    def mirror_display_rows(self) -> tuple[str, ...]:
        return tuple(
            " ".join(self.mirror_by_physical[key.normal] for key in KEYS[row * 5 : row * 5 + 5])
            for row in range(3)
        )

    def as_rows(self) -> tuple[tuple[PhysicalKey, str], ...]:
        return tuple((key, self.mirror_by_physical[key.normal]) for key in KEYS)


def conventional_layout() -> Layout:
    # Alphabet positions from Y U I O P / H J K L / N M; punctuation is fixed.
    return Layout.from_letters(tuple("yuiophjklnm"))
