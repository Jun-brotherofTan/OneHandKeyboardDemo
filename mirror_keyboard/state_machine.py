"""Thread-safe view state and mode transitions for the keyboard test."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock
from typing import Callable, Mapping

from layout import KEYS
from mirror_keyboard.layout_loader import KeyboardProfile


class MirrorState(str, Enum):
    NORMAL = "NORMAL"
    WAITING_FOR_SECOND_TAP = "WAITING_FOR_SECOND_TAP"
    ONE_SHOT = "MIRROR ONE-SHOT"
    HELD = "MIRROR HELD"


@dataclass(frozen=True)
class ViewState:
    profile_name: str
    mode: str
    mirror_status: str
    shortcut_status: str
    labels: Mapping[str, str]
    highlighted_key: str | None
    event_text: str


@dataclass(frozen=True)
class KeyEmission:
    physical_key: str
    output: str
    mode: str


class KeyboardStateMachine:
    def __init__(self, profile: KeyboardProfile, *, double_tap_ms: int = 300):
        if double_tap_ms < 1:
            raise ValueError("double_tap_ms must be at least 1")
        self.profile = profile
        self.double_tap_ms = double_tap_ms
        self._mirror_state = MirrorState.NORMAL
        self._second_tap_deadline: float | None = None
        self._shortcut_active = False
        self._highlighted_key: str | None = None
        self._event_text = "Ready"
        self._modifier_event = "No mirror modifier event detected yet"
        self._listeners: list[Callable[[ViewState], None]] = []
        self._lock = RLock()

    def subscribe(self, listener: Callable[[ViewState], None]) -> None:
        with self._lock:
            self._listeners.append(listener)
        listener(self.snapshot())

    def _publish(self) -> None:
        state = self.snapshot()
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(state)

    def snapshot(self) -> ViewState:
        with self._lock:
            if self._shortcut_active:
                mode = "SHORTCUT"
                labels = {
                    key.normal: self.profile.shortcut_mapping.get(key.normal, "—")
                    for key in KEYS
                }
            elif self._mirror_state in {MirrorState.ONE_SHOT, MirrorState.HELD}:
                mode = self._mirror_state.value
                labels = dict(self.profile.mirror_mapping)
            else:
                mode = "NORMAL"
                labels = dict(self.profile.normal_mapping)

            if self._mirror_state == MirrorState.WAITING_FOR_SECOND_TAP:
                mirror_status = "WAITING FOR SECOND TAP"
            elif self._mirror_state == MirrorState.ONE_SHOT:
                mirror_status = "ONE-SHOT ARMED"
            elif self._mirror_state == MirrorState.HELD:
                mirror_status = "HELD ON"
            else:
                mirror_status = "OFF"
            shortcut_status = (
                self.profile.shortcut_profile_name
                if self.profile.shortcut_mapping
                else "not loaded (Ctrl+Alt+S preview)"
            )
            return ViewState(
                profile_name=self.profile.name,
                mode=mode,
                mirror_status=mirror_status,
                shortcut_status=shortcut_status,
                labels=labels,
                highlighted_key=self._highlighted_key,
                event_text=f"{self._modifier_event} | {self._event_text}",
            )

    def note_modifier_event(self, description: str) -> None:
        with self._lock:
            self._modifier_event = description
        self._publish()

    def advance_time(self, now: float) -> None:
        changed = False
        with self._lock:
            if (
                self._mirror_state == MirrorState.WAITING_FOR_SECOND_TAP
                and self._second_tap_deadline is not None
                and now >= self._second_tap_deadline
            ):
                self._mirror_state = MirrorState.ONE_SHOT
                self._second_tap_deadline = None
                changed = True
        if changed:
            self._publish()

    def right_alt_tap(self, now: float) -> None:
        self.advance_time(now)
        with self._lock:
            if self._mirror_state == MirrorState.HELD:
                self._mirror_state = MirrorState.NORMAL
                self._second_tap_deadline = None
            elif self._mirror_state == MirrorState.WAITING_FOR_SECOND_TAP:
                self._mirror_state = MirrorState.HELD
                self._second_tap_deadline = None
            else:
                self._mirror_state = MirrorState.WAITING_FOR_SECOND_TAP
                self._second_tap_deadline = now + self.double_tap_ms / 1000
        self._publish()

    def press(self, physical_key: str, *, now: float, shifted: bool = False) -> KeyEmission:
        key = physical_key.lower()
        if key not in self.profile.normal_mapping:
            raise ValueError(f"Not an active physical key: {physical_key}")
        self.advance_time(now)
        with self._lock:
            if self._mirror_state == MirrorState.WAITING_FOR_SECOND_TAP:
                self._mirror_state = MirrorState.ONE_SHOT
                self._second_tap_deadline = None

            if self._shortcut_active:
                mode = "SHORTCUT"
                output = self.profile.shortcut_mapping.get(
                    key, self.profile.normal_mapping[key]
                )
            elif self._mirror_state in {MirrorState.ONE_SHOT, MirrorState.HELD}:
                mode = self._mirror_state.value
                output = self.profile.mirror_mapping[key]
            else:
                mode = "NORMAL"
                output = self.profile.normal_mapping[key]

            if shifted and mode != "SHORTCUT":
                output = _shift_output(output)
            if self._mirror_state == MirrorState.ONE_SHOT:
                self._mirror_state = MirrorState.NORMAL
            self._highlighted_key = key
            self._event_text = f"Pressed {key.upper()} -> emitted {output or '(no shortcut assigned)'}"
        self._publish()
        return KeyEmission(key, output, mode)

    def toggle_shortcut(self) -> None:
        with self._lock:
            self._shortcut_active = not self._shortcut_active
        self._publish()

    def switch_profile(self, profile: KeyboardProfile) -> None:
        with self._lock:
            self.profile = profile
            self._highlighted_key = None
            self._event_text = f"Loaded {profile.name}"
        self._publish()


def _shift_output(output: str) -> str:
    shifted_symbols = dict(zip("1234567890-=[]\\;'`,./", "!@#$%^&*()_+{}|:\"~<>?"))
    return "".join(
        character.upper() if character.isalpha() else shifted_symbols.get(character, character)
        for character in output
    )