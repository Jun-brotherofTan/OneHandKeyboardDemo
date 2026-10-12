"""Run the Windows-only one-handed keyboard and visual overlay test."""

from __future__ import annotations

import argparse
import os
import sys

from mirror_keyboard.layout_loader import load_layout_profile
from mirror_keyboard.overlay_ui import KeyboardOverlay
from mirror_keyboard.session import KeyboardTestSession
from mirror_keyboard.state_machine import KeyboardStateMachine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", default="layout_A.csv", help="layout mapping CSV")
    parser.add_argument(
        "--shortcuts",
        "--shortcut-profile",
        dest="shortcut_profile",
        help="optional CSV with physical_key,shortcut columns",
    )
    parser.add_argument("--double-tap-ms", type=int, default=300)
    parser.add_argument(
        "--mirror-key",
        choices=("right-alt", "caps-lock", "f12"),
        default="right-alt",
        help="physical key used for single/double-tap mirror activation",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log Right Alt and Korean IME-related low-level key events",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("the keyboard tester is Windows-only")
    if args.double_tap_ms < 1:
        parser.error("--double-tap-ms must be at least 1")

    try:
        profile = load_layout_profile(args.layout, args.shortcut_profile)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    state_machine = KeyboardStateMachine(profile, double_tap_ms=args.double_tap_ms)
    session = KeyboardTestSession(
        state_machine,
        layout_path=args.layout,
        shortcut_path=args.shortcut_profile,
        mirror_key=args.mirror_key,
        verbose=args.verbose,
    )
    overlay = KeyboardOverlay(session)
    session.attach_overlay(overlay)
    try:
        session.start()
        overlay.run()
    except (OSError, RuntimeError) as error:
        session.report_error(str(error))
        session.request_shutdown()
        session.finish_shutdown()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())