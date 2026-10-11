"""Tkinter visual keyboard overlay. All widget work stays on the Tk thread."""

from __future__ import annotations

import os
from dataclasses import replace

from layout import KEYS
from mirror_keyboard.state_machine import ViewState


def fit_label_font_size(text: str, maximum_width: int, measure, *, maximum_size: int = 20) -> int:
    size = maximum_size
    while size > 7 and measure(text, size) > maximum_width:
        size -= 1
    return size


def wrap_label_text(text: str, maximum_width: int, measure, font_size: int) -> str:
    """Wrap even long unbroken shortcut labels without dropping characters."""
    lines = []
    current = ""
    for character in text:
        if current and measure(current + character, font_size) > maximum_width:
            lines.append(current)
            current = character
        else:
            current += character
    if current or not lines:
        lines.append(current)
    return "\n".join(lines)


class KeyboardOverlay:
    def __init__(self, session):
        import tkinter as tk
        from tkinter import font

        self.tk = tk
        self.font_module = font
        self.session = session
        self.root = tk.Tk()
        self.root.title("One-Hand Keyboard Test")
        self.root.geometry("720x390+40+40")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.focusmodel("passive")
        self.root.protocol("WM_DELETE_WINDOW", self.session.request_shutdown)
        self.root.configure(bg="#e6e9ed")

        self.canvas = tk.Canvas(
            self.root,
            width=700,
            height=370,
            bg="#e6e9ed",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.header = self.canvas.create_text(
            18, 14, anchor="nw", text="ONE-HAND KEYBOARD TEST", fill="#20262e",
            font=("Segoe UI", 14, "bold"),
        )
        self.close_button = self.canvas.create_text(
            682, 14, anchor="ne", text="CLOSE", fill="#5b6571", font=("Segoe UI", 9, "bold")
        )
        self.canvas.tag_bind(self.close_button, "<Button-1>", lambda _event: self.session.request_shutdown())
        self.mode_text = self.canvas.create_text(
            18, 44, anchor="nw", text="NORMAL", fill="#32404d", font=("Segoe UI", 12, "bold")
        )
        self.key_items = {}
        self._build_keys()
        self.inactive_text = self.canvas.create_text(
            490, 150, anchor="center", width=190,
            text="OTHER KEYS\npassed through to Windows",
            fill="#a5abb2", font=("Segoe UI", 12, "bold"), justify="center",
        )
        self.profile_text = self.canvas.create_text(18, 250, anchor="nw", fill="#20262e")
        self.status_text = self.canvas.create_text(18, 274, anchor="nw", fill="#20262e")
        self.hotkeys_text = self.canvas.create_text(
            18,
            302,
            anchor="nw",
            text="Profiles: Ctrl+Alt+1..5    Shortcut: Ctrl+Alt+S    Emergency exit: Ctrl+Alt+Esc",
            fill="#59636e",
            font=("Segoe UI", 9),
        )
        self.event_text = self.canvas.create_text(
            18, 335, anchor="nw", fill="#20262e", font=("Segoe UI", 10, "bold")
        )
        self._state = self.session.state_machine.snapshot()
        self._highlight_deadline = 0.0
        self._closed = False
        self._render(self._state)

    def _build_keys(self) -> None:
        row_text = ("QWERT", "ASDFG", "ZXCVB")
        for row, keys in enumerate(row_text):
            x_offset = row * 17
            y = 89 + row * 53
            for column, key in enumerate(keys):
                x = 22 + x_offset + column * 88
                y1 = y
                rect = self.canvas.create_rectangle(
                    x, y1, x + 78, y1 + 44, fill="#fbfcfd", outline="#8b96a2", width=2
                )
                label = self.canvas.create_text(
                    x + 39, y1 + 22, text=key, fill="#20262e", font=("Segoe UI", 20, "bold")
                )
                self.key_items[key.lower()] = (rect, label)

    @staticmethod
    def _mode_colors(mode: str) -> tuple[str, str]:
        return {
            "NORMAL": ("#fbfcfd", "#34404c"),
            "MIRROR ONE-SHOT": ("#ffe2a8", "#9a5a00"),
            "MIRROR HELD": ("#ffb8aa", "#8b2415"),
            "SHORTCUT": ("#bdeee5", "#006b5b"),
        }.get(mode, ("#fbfcfd", "#34404c"))

    def _render(self, state: ViewState) -> None:
        self._state = state
        mode_background, mode_foreground = self._mode_colors(state.mode)
        self.canvas.itemconfigure(self.mode_text, text=state.mode, fill=mode_foreground)
        self.canvas.itemconfigure(self.header, fill=mode_foreground)
        for physical_key, (rectangle, label) in self.key_items.items():
            output = state.labels.get(physical_key, physical_key)
            highlighted = physical_key == state.highlighted_key
            background = "#ffd450" if highlighted else mode_background
            foreground = "#1a1a1a" if highlighted else mode_foreground
            self.canvas.itemconfigure(rectangle, fill=background)
            value = output or "—"
            size = fit_label_font_size(
                value,
                68,
                lambda text, font_size: self.font_module.Font(
                    family="Segoe UI", size=font_size, weight="bold"
                ).measure(text),
            )
            display_value = wrap_label_text(
                value,
                68,
                lambda text, font_size: self.font_module.Font(
                    family="Segoe UI", size=font_size, weight="bold"
                ).measure(text),
                size,
            )
            self.canvas.itemconfigure(
                label,
                text=value.upper() if len(value) == 1 else display_value,
                font=("Segoe UI", size, "bold"),
                width=68,
            )
        self.canvas.itemconfigure(self.profile_text, text=f"Profile: {state.profile_name}")
        self.canvas.itemconfigure(
            self.status_text,
            text=(
                f"Mirror: {state.mirror_status}    Shortcut profile: {state.shortcut_status}"
                "    Active area: QWERT / ASDFG / ZXCVB"
            ),
        )
        self.canvas.itemconfigure(self.event_text, text=state.event_text)
        if state.highlighted_key:
            self._highlight_deadline = self.session.clock() + 0.25

    def _make_nonactivating(self) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW")
            set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW")
            style = get_window_long(hwnd, -20)
            set_window_long(hwnd, -20, style | 0x08000000 | 0x00000080)
        except (AttributeError, OSError):
            pass

    def _poll(self) -> None:
        if self._closed:
            return
        self.session.advance_time()
        while True:
            try:
                event_name, payload = self.session.events.get_nowait()
            except Exception:
                break
            if event_name == "state":
                self._render(payload)
            elif event_name == "error":
                self.canvas.itemconfigure(self.event_text, text=str(payload), fill="#a52819")
            elif event_name == "shutdown":
                self.session.finish_shutdown()
                return
        if self._state.highlighted_key and self.session.clock() >= self._highlight_deadline:
            self._render(replace(self._state, highlighted_key=None))
        self.root.after(25, self._poll)

    def run(self) -> None:
        self.root.update_idletasks()
        self._make_nonactivating()
        self.root.after(25, self._poll)
        self.root.mainloop()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass
