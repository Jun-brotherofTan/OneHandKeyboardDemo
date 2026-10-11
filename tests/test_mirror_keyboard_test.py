import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from layout import KEYS
from mirror_keyboard.layout_loader import load_layout_profile
from mirror_keyboard.keyboard_hook import (
    VK_CONTROL,
    VK_CAPITAL,
    VK_ESCAPE,
    VK_HANGUL,
    VK_MENU,
    VK_LMENU,
    VK_RMENU,
    WM_KEYDOWN,
    WM_KEYUP,
    LLKHF_EXTENDED,
    LLKHF_INJECTED,
    WindowsKeyboardHook,
)
from mirror_keyboard.overlay_ui import fit_label_font_size, wrap_label_text
from mirror_keyboard.session import KeyboardTestSession
from mirror_keyboard.state_machine import KeyboardStateMachine


ROOT = Path(__file__).resolve().parents[1]


class FakeHook:
    def __init__(self, events):
        self.events = events

    def request_stop(self):
        self.events.append("hook-stop")

    def join(self):
        self.events.append("hook-join")


class FakeOverlay:
    def __init__(self, events):
        self.events = events

    def close(self):
        self.events.append("overlay-close")


class FakeLogger:
    def __init__(self, events):
        self.events = events

    def record(self, *_args):
        self.events.append("log-record")

    def close(self):
        self.events.append("logger-close")


class FakeHookSession:
    def __init__(self):
        self.taps = 0
        self.shutdowns = 0
        self.modifier_events = []

    def right_alt_tap(self):
        self.taps += 1

    def request_shutdown(self):
        self.shutdowns += 1

    def report_modifier_event(self, description):
        self.modifier_events.append(description)


class MirrorKeyboardTestTests(unittest.TestCase):
    def setUp(self):
        self.profile_a = load_layout_profile(ROOT / "layout_A.csv")
        self.profile_c = load_layout_profile(ROOT / "layout_C.csv")

    def test_profile_loading_builds_normal_and_mirror_view_mappings(self):
        self.assertEqual(self.profile_c.normal_mapping["q"], "q")
        self.assertEqual(self.profile_c.mirror_mapping["q"], "y")
        self.assertEqual(self.profile_c.mirror_mapping["w"], "p")
        self.assertEqual(len(self.profile_c.mirror_mapping), len(KEYS))

    def test_normal_mode_displays_normal_mapping(self):
        state = KeyboardStateMachine(self.profile_c).snapshot()
        self.assertEqual(state.mode, "NORMAL")
        self.assertEqual(state.labels["q"], "q")
        self.assertEqual(state.labels["w"], "w")

    def test_one_shot_mirror_updates_visible_mapping(self):
        machine = KeyboardStateMachine(self.profile_c)
        machine.right_alt_tap(1.0)
        machine.advance_time(1.301)
        state = machine.snapshot()
        self.assertEqual(state.mode, "MIRROR ONE-SHOT")
        self.assertEqual(state.labels["q"], "y")

    def test_held_mirror_keeps_visible_mapping_latched(self):
        machine = KeyboardStateMachine(self.profile_c)
        machine.right_alt_tap(1.0)
        machine.right_alt_tap(1.1)
        state = machine.snapshot()
        self.assertEqual(state.mode, "MIRROR HELD")
        self.assertEqual(state.labels["q"], "y")
        machine.press("q", now=1.2)
        self.assertEqual(machine.snapshot().mode, "MIRROR HELD")

    def test_key_press_after_one_shot_restores_normal_labels(self):
        machine = KeyboardStateMachine(self.profile_c)
        machine.right_alt_tap(1.0)
        emission = machine.press("q", now=1.1)
        self.assertEqual(emission.output, "y")
        self.assertEqual(machine.snapshot().mode, "NORMAL")
        self.assertEqual(machine.snapshot().labels["q"], "q")

    def test_shifted_physical_key_emits_shifted_output(self):
        machine = KeyboardStateMachine(self.profile_c)
        normal = machine.press("q", now=1.0, shifted=True)
        machine.right_alt_tap(2.0)
        mirrored = machine.press("q", now=2.301, shifted=True)
        self.assertEqual(normal.output, "Q")
        self.assertEqual(mirrored.output, "Y")

    def test_shortcut_mapping_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            shortcut_csv = Path(directory) / "shortcuts.csv"
            shortcut_csv.write_text(
                "physical_key,shortcut\nq,self.\nw,import \n",
                encoding="utf-8",
            )
            profile = load_layout_profile(ROOT / "layout_C.csv", shortcut_csv)
        machine = KeyboardStateMachine(profile)
        machine.toggle_shortcut()
        state = machine.snapshot()
        self.assertEqual(state.mode, "SHORTCUT")
        self.assertEqual(state.labels["q"], "self.")
        self.assertEqual(machine.press("q", now=1.0).output, "self.")

    def test_shortcut_preview_without_profile_preserves_normal_key_output(self):
        machine = KeyboardStateMachine(self.profile_c)
        machine.toggle_shortcut()
        self.assertEqual(machine.snapshot().labels["q"], "—")
        self.assertEqual(machine.press("q", now=1.0).output, "q")

    def test_profile_switch_replaces_visible_mapping(self):
        machine = KeyboardStateMachine(self.profile_a)
        machine.switch_profile(self.profile_c)
        state = machine.snapshot()
        self.assertEqual(state.profile_name, "layout_C.csv")
        self.assertEqual(state.labels["q"], "q")
        machine.right_alt_tap(1.0)
        machine.advance_time(1.301)
        self.assertEqual(machine.snapshot().labels["q"], "y")

    def test_highlight_targets_physical_source_key(self):
        machine = KeyboardStateMachine(self.profile_c)
        machine.right_alt_tap(1.0)
        emission = machine.press("q", now=1.301)
        state = machine.snapshot()
        self.assertEqual(emission.output, "y")
        self.assertEqual(state.highlighted_key, "q")
        self.assertIn("Pressed Q -> emitted y", state.event_text)

    def test_emergency_exit_stops_hook_closes_overlay_and_flushes_logger(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            session = KeyboardTestSession(
                KeyboardStateMachine(self.profile_a),
                layout_path=ROOT / "layout_A.csv",
                hook=FakeHook(events),
                logger=FakeLogger(events),
            )
            session.attach_overlay(FakeOverlay(events))
            session.request_shutdown()
            session.finish_shutdown()

        self.assertEqual(
            events,
            ["hook-stop", "hook-join", "overlay-close", "logger-close"],
        )
        self.assertTrue(session.shutdown_complete)

    def test_long_shortcut_label_shrinks_without_truncating(self):
        measured = lambda text, size: len(text) * size * 0.6
        label = ".append((self, return_value))"
        size = fit_label_font_size(label, 68, measured)
        self.assertLess(size, 20)
        self.assertGreaterEqual(size, 7)
        self.assertEqual(label, ".append((self, return_value))")
        wrapped = wrap_label_text(label, 68, measured, size)
        self.assertEqual(wrapped.replace("\n", ""), label)
        self.assertTrue(all(measured(line, size) <= 68 for line in wrapped.splitlines()))

    def test_hook_uses_right_alt_taps_only_and_ignores_left_alt(self):
        session = FakeHookSession()
        hook = WindowsKeyboardHook(session)
        clock_values = iter((1.0, 1.7, 2.0, 2.2))
        key_states = {VK_RMENU: 0, VK_LMENU: 0}
        get_async = lambda key: key_states.get(key, 0)

        with patch("mirror_keyboard.keyboard_hook.time.monotonic", side_effect=lambda: next(clock_values)):
            self.assertFalse(hook._handle_event(VK_RMENU, WM_KEYDOWN, get_async))
            self.assertFalse(hook._handle_event(VK_RMENU, WM_KEYUP, get_async))
            self.assertFalse(hook._handle_event(VK_LMENU, WM_KEYDOWN, get_async))
            self.assertFalse(hook._handle_event(VK_LMENU, WM_KEYUP, get_async))
            self.assertFalse(hook._handle_event(VK_RMENU, WM_KEYDOWN, get_async))
            self.assertFalse(hook._handle_event(VK_RMENU, WM_KEYUP, get_async))

        self.assertEqual(session.taps, 1)
        self.assertTrue(any("Right Alt" in event for event in session.modifier_events))

    def test_hangul_virtual_key_with_extended_right_alt_scan_activates_mirror(self):
        session = FakeHookSession()
        hook = WindowsKeyboardHook(session)
        key_states = {VK_HANGUL: 0}
        get_async = lambda key: key_states.get(key, 0)

        with patch("mirror_keyboard.keyboard_hook.time.monotonic", side_effect=(1.0, 1.1)):
            handled_down = hook._handle_event(
                VK_HANGUL, WM_KEYDOWN, get_async, scan_code=0x38, flags=LLKHF_EXTENDED
            )
            handled_up = hook._handle_event(
                VK_HANGUL, WM_KEYUP, get_async, scan_code=0x38, flags=LLKHF_EXTENDED
            )

        self.assertFalse(handled_down)
        self.assertFalse(handled_up)
        self.assertEqual(session.taps, 1)

    def test_extended_scan_code_identifies_right_alt_when_vk_is_generic_menu(self):
        session = FakeHookSession()
        hook = WindowsKeyboardHook(session)
        with patch("mirror_keyboard.keyboard_hook.time.monotonic", side_effect=(1.0, 1.1)):
            hook._handle_event(VK_MENU, WM_KEYDOWN, lambda _key: 0, scan_code=0x38, flags=LLKHF_EXTENDED)
            hook._handle_event(VK_MENU, WM_KEYUP, lambda _key: 0, scan_code=0x38, flags=LLKHF_EXTENDED)
        self.assertEqual(session.taps, 1)

    def test_non_extended_left_alt_scan_does_not_activate_mirror(self):
        session = FakeHookSession()
        hook = WindowsKeyboardHook(session)
        with patch("mirror_keyboard.keyboard_hook.time.monotonic") as clock:
            handled = hook._handle_event(
                VK_LMENU, WM_KEYDOWN, lambda _key: 0, scan_code=0x38, flags=0
            )
        self.assertFalse(handled)
        clock.assert_not_called()
        self.assertEqual(session.taps, 0)

    def test_caps_lock_can_be_selected_as_mirror_modifier(self):
        session = FakeHookSession()
        hook = WindowsKeyboardHook(session, mirror_key="caps-lock")
        with patch("mirror_keyboard.keyboard_hook.time.monotonic", side_effect=(1.0, 1.1)):
            self.assertTrue(hook._handle_event(VK_CAPITAL, WM_KEYDOWN, lambda _key: 0))
            self.assertTrue(hook._handle_event(VK_CAPITAL, WM_KEYUP, lambda _key: 0))
        self.assertEqual(session.taps, 1)

    def test_verbose_right_alt_log_includes_physical_event_fields(self):
        hook = WindowsKeyboardHook(FakeHookSession(), verbose=True)
        output = StringIO()
        with redirect_stdout(output):
            hook._log_key_event(
                VK_HANGUL,
                0x38,
                LLKHF_EXTENDED | LLKHF_INJECTED,
                WM_KEYUP,
                True,
            )
        message = output.getvalue()
        self.assertIn("vk=0x15", message)
        self.assertIn("scan=0x38", message)
        self.assertIn("extended=True", message)
        self.assertIn("up", message)
        self.assertIn("injected=True", message)

    def test_cli_exposes_alternative_mirror_key_and_verbose_options(self):
        from mirror_keyboard_test import build_parser

        args = build_parser().parse_args(
            ["--layout", "layout_C.csv", "--mirror-key", "f12", "--verbose"]
        )
        self.assertEqual(args.mirror_key, "f12")
        self.assertTrue(args.verbose)

    def test_emergency_hotkey_event_requests_shutdown(self):
        session = FakeHookSession()
        hook = WindowsKeyboardHook(session)
        states = {VK_CONTROL: 0x8000, VK_MENU: 0x8000}
        handled = hook._handle_event(
            VK_ESCAPE, WM_KEYDOWN, lambda key: states.get(key, 0)
        )
        self.assertTrue(handled)
        self.assertEqual(session.shutdowns, 1)


if __name__ == "__main__":
    unittest.main()