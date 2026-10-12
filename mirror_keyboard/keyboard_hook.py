"""Selective Windows low-level keyboard hook for the one-handed test area."""

from __future__ import annotations

import os
import threading
import time


ACTIVE_VIRTUAL_KEYS = {
    ord(character): character.lower() for character in "QWERTASDFGZXCVB"
}
VK_RMENU = 0xA5
VK_LMENU = 0xA4
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_HANGUL = 0x15
VK_IME_ON = 0x16
VK_HANJA = 0x19
VK_CONVERT = 0x1C
VK_NONCONVERT = 0x1D
VK_MODECHANGE = 0x1F
VK_PROCESSKEY = 0xE5
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_ESCAPE = 0x1B
VK_S = ord("S")
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
LLKHF_EXTENDED = 0x01
LLKHF_UP = 0x80
MAX_RIGHT_ALT_TAP_MS = 500
RIGHT_ALT_SCAN_CODE = 0x38
HANGUL_RELATED_KEYS = {
    VK_RMENU,
    VK_LMENU,
    VK_MENU,
    VK_HANGUL,
    VK_IME_ON,
    VK_HANJA,
    VK_CONVERT,
    VK_NONCONVERT,
    VK_MODECHANGE,
    VK_PROCESSKEY,
}
MIRROR_KEY_VIRTUAL_KEYS = {"caps-lock": VK_CAPITAL, "f12": 0x7B}


class WindowsKeyboardHook:
    def __init__(self, session, *, mirror_key: str = "right-alt", verbose: bool = False):
        if mirror_key not in {"right-alt", *MIRROR_KEY_VIRTUAL_KEYS}:
            raise ValueError(f"Unsupported mirror key: {mirror_key}")
        self.session = session
        self.mirror_key = mirror_key
        self.verbose = verbose
        self._thread = None
        self._thread_id = None
        self._hook_handle = None
        self._stop_requested = threading.Event()
        self._ready = threading.Event()
        self._startup_error = None
        self._mirror_key_started = None
        self._pressed_active = set()
        self._pressed_hotkeys = set()

    def start(self) -> None:
        if os.name != "nt":
            raise RuntimeError("The keyboard tester input hook is supported on Windows only.")
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="mirror-keyboard-hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Timed out starting the Windows keyboard hook.")
        if self._startup_error is not None:
            raise RuntimeError(f"Could not start the Windows keyboard hook: {self._startup_error}")

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.WPARAM),
            ]

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )

        def call_next(code, message_id, data):
            return user32.CallNextHookEx(self._hook_handle, code, message_id, data)

        @callback_type
        def hook_callback(code, message_id, data_pointer):
            if code < 0:
                return call_next(code, message_id, data_pointer)
            event = ctypes.cast(data_pointer, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            injected = bool(event.flags & LLKHF_INJECTED)
            self._log_key_event(
                event.vkCode,
                event.scanCode,
                event.flags,
                message_id,
                injected,
            )
            try:
                handled = self.dispatch_hook_event(
                    event.vkCode,
                    message_id,
                    user32.GetAsyncKeyState,
                    scan_code=event.scanCode,
                    flags=event.flags,
                    injected=injected,
                )
            except Exception as error:
                self.session.report_error(f"Keyboard hook error: {error}")
                handled = False
            if handled:
                return 1
            return call_next(code, message_id, data_pointer)

        self._callback_reference = hook_callback
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetAsyncKeyState.argtypes = [wintypes.INT]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            callback_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.CallNextHookEx.restype = wintypes.LPARAM
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

        try:
            self._hook_handle = user32.SetWindowsHookExW(
                13, hook_callback, kernel32.GetModuleHandleW(None), 0
            )
            if not self._hook_handle:
                self._startup_error = ctypes.WinError()
                return
            self._ready.set()
            while not self._stop_requested.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self._startup_error = error
            self.session.report_error(f"Keyboard hook stopped: {error}")
        finally:
            self._ready.set()
            if self._hook_handle:
                user32.UnhookWindowsHookEx(self._hook_handle)
                self._hook_handle = None

    @staticmethod
    def _is_down(get_async_key_state, virtual_key: int) -> bool:
        return bool(get_async_key_state(virtual_key) & 0x8000)

    @staticmethod
    def _is_physical_right_alt(virtual_key: int, scan_code: int, flags: int) -> bool:
        if virtual_key in {VK_RMENU, VK_HANGUL}:
            return True
        return scan_code == RIGHT_ALT_SCAN_CODE and bool(flags & LLKHF_EXTENDED)

    def _is_mirror_key(self, virtual_key: int, scan_code: int, flags: int) -> bool:
        if self.mirror_key == "right-alt":
            return self._is_physical_right_alt(virtual_key, scan_code, flags)
        return virtual_key == MIRROR_KEY_VIRTUAL_KEYS[self.mirror_key]

    def _log_key_event(
        self,
        virtual_key: int,
        scan_code: int,
        flags: int,
        message_id: int,
        injected: bool,
    ) -> None:
        if not self.verbose or (
            virtual_key not in HANGUL_RELATED_KEYS and scan_code != RIGHT_ALT_SCAN_CODE
        ):
            return
        is_down = message_id in {WM_KEYDOWN, WM_SYSKEYDOWN}
        direction = "down" if is_down else "up"
        extended = bool(flags & LLKHF_EXTENDED)
        print(
            "Keyboard debug: "
            f"vk=0x{virtual_key:02X} scan=0x{scan_code:02X} "
            f"extended={extended} {direction} injected={injected}",
            flush=True,
        )

    def _handle_event(
        self,
        virtual_key: int,
        message_id: int,
        get_async_key_state,
        *,
        scan_code: int = 0,
        flags: int = 0,
    ) -> bool:
        is_down = message_id in {WM_KEYDOWN, WM_SYSKEYDOWN}
        is_up = message_id in {WM_KEYUP, WM_SYSKEYUP}
        if not is_down and not is_up:
            return False

        if is_up and virtual_key in self._pressed_hotkeys:
            self._pressed_hotkeys.discard(virtual_key)
            return True

        control = self._is_down(get_async_key_state, VK_CONTROL)
        alt = self._is_down(get_async_key_state, VK_MENU)
        if is_down and control and alt:
            if virtual_key in {VK_ESCAPE, VK_S, *(ord(str(index)) for index in range(1, 6))}:
                if virtual_key not in self._pressed_hotkeys:
                    self._pressed_hotkeys.add(virtual_key)
                    if virtual_key == VK_ESCAPE:
                        self.session.request_shutdown()
                    elif virtual_key in {ord(str(index)) for index in range(1, 6)}:
                        self.session.switch_profile(chr(virtual_key))
                    else:
                        self.session.toggle_shortcut_mode()
                return True

        if self._is_mirror_key(virtual_key, scan_code, flags):
            physical_key = (
                "Right Alt"
                if self.mirror_key == "right-alt"
                else self.mirror_key.replace("-", " ").title()
            )
            event_label = (
                f"Detected mirror modifier: {physical_key} "
                f"(VK 0x{virtual_key:02X}, scan 0x{scan_code:02X}, "
                f"extended={bool(flags & LLKHF_EXTENDED)}, "
                f"{'down' if is_down else 'up'})"
            )
            self.session.report_modifier_event(event_label)
            if is_down:
                if self._mirror_key_started is None:
                    self._mirror_key_started = time.monotonic()
            elif self._mirror_key_started is not None:
                duration_ms = (time.monotonic() - self._mirror_key_started) * 1000
                self._mirror_key_started = None
                if duration_ms <= MAX_RIGHT_ALT_TAP_MS:
                    self.session.right_alt_tap()
            return self.mirror_key != "right-alt"

        if virtual_key == VK_LMENU:
            return False

        physical_key = ACTIVE_VIRTUAL_KEYS.get(virtual_key)
        if physical_key is None:
            return False

        if control or self._is_down(get_async_key_state, VK_LMENU):
            return False
        if is_down:
            if virtual_key in self._pressed_active:
                return True
            emission = self.session.handle_physical_key(
                physical_key,
                shifted=self._is_down(get_async_key_state, VK_SHIFT),
            )
            if not emission.suppress_original:
                return False
            self._pressed_active.add(virtual_key)
            if emission.output:
                self._emit_unicode(emission.output)
            return True
        if virtual_key in self._pressed_active:
            self._pressed_active.discard(virtual_key)
            return True
        return False

    def dispatch_hook_event(
        self,
        virtual_key: int,
        message_id: int,
        get_async_key_state,
        *,
        scan_code: int = 0,
        flags: int = 0,
        injected: bool = False,
    ) -> bool:
        """Return whether the physical event is suppressed; ignore synthetic input."""
        if injected:
            return False
        return self._handle_event(
            virtual_key,
            message_id,
            get_async_key_state,
            scan_code=scan_code,
            flags=flags,
        )

    @staticmethod
    def _emit_unicode(text: str) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        keyeventf_keyup = 0x0002
        keyeventf_unicode = 0x0004
        for character in text:
            encoded = character.encode("utf-16-le")
            for offset in range(0, len(encoded), 2):
                code_unit = int.from_bytes(encoded[offset : offset + 2], "little")
                user32.keybd_event(0, code_unit, keyeventf_unicode, 0)
                user32.keybd_event(0, code_unit, keyeventf_unicode | keyeventf_keyup, 0)

    def request_stop(self) -> None:
        self._stop_requested.set()
        if self._thread_id is not None:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def join(self, timeout: float = 3.0) -> None:
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)
