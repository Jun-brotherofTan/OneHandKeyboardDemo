"""Coordinate keyboard state, profile changes, overlay updates, and shutdown."""

from __future__ import annotations

import queue
import sys
from pathlib import Path
from threading import Event
from time import monotonic

from mirror_keyboard.layout_loader import load_layout_profile, standard_profile_paths
from mirror_keyboard.state_machine import KeyboardStateMachine, ViewState
from mirror_keyboard.usage_logger import UsageLogger


class KeyboardTestSession:
    def __init__(
        self,
        state_machine: KeyboardStateMachine,
        *,
        layout_path: str | Path,
        shortcut_path: str | Path | None = None,
        hook=None,
        logger=None,
        clock=monotonic,
    ):
        self.state_machine = state_machine
        self.layout_path = Path(layout_path).resolve()
        self.shortcut_path = Path(shortcut_path).resolve() if shortcut_path else None
        self.profile_paths = standard_profile_paths(layout_path)
        self.hook = hook
        self.logger = logger or UsageLogger()
        self.clock = clock
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.shutdown_requested = Event()
        self.shutdown_complete = False
        self.overlay = None
        self.state_machine.subscribe(lambda state: self.events.put(("state", state)))

    def attach_overlay(self, overlay) -> None:
        self.overlay = overlay

    def start(self) -> None:
        if self.hook is None:
            from mirror_keyboard.keyboard_hook import WindowsKeyboardHook

            self.hook = WindowsKeyboardHook(self)
        self.hook.start()
        print(f"Active profile: {self.state_machine.profile.name}", flush=True)

    def advance_time(self) -> None:
        self.state_machine.advance_time(self.clock())

    def right_alt_tap(self) -> None:
        self.state_machine.right_alt_tap(self.clock())

    def handle_physical_key(self, physical_key: str, *, shifted: bool = False) -> str:
        result = self.state_machine.press(
            physical_key, now=self.clock(), shifted=shifted
        )
        self.logger.record(
            self.state_machine.profile.name,
            result.mode,
            result.physical_key,
            result.output,
        )
        return result.output

    def toggle_shortcut_mode(self) -> None:
        self.state_machine.toggle_shortcut()

    def switch_profile(self, number: str) -> None:
        path = self.profile_paths.get(number)
        if path is None or not path.is_file():
            self.events.put(("error", f"No layout profile for hotkey {number}: {path}"))
            return
        try:
            profile = load_layout_profile(path, self.shortcut_path)
        except (OSError, ValueError) as error:
            self.events.put(("error", f"Could not load {path.name}: {error}"))
            return
        self.layout_path = path
        self.state_machine.switch_profile(profile)
        print(f"Active profile: {profile.name}", flush=True)

    def request_shutdown(self) -> None:
        if self.shutdown_requested.is_set():
            return
        self.shutdown_requested.set()
        if self.hook is not None:
            self.hook.request_stop()
        self.events.put(("shutdown", None))

    def finish_shutdown(self) -> None:
        if self.shutdown_complete:
            return
        if self.hook is not None:
            self.hook.join()
        if self.overlay is not None:
            self.overlay.close()
        self.logger.close()
        self.shutdown_complete = True

    def report_error(self, message: str) -> None:
        self.events.put(("error", message))
        print(message, file=sys.stderr, flush=True)
