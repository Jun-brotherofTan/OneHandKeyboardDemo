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
MAX_RIGHT_ALT_TAP_MS = 500


class WindowsKeyboardHook:
    def __init__(self, session):
        self.session = session
        self._thread = None
        self._thread_id = None
        self._hook_handle = None
        self._stop_requested = threading.Event()
        self._ready = threading.Event()
        self._startup_error = None
        self._right_alt_started = None
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
            if event.flags & LLKHF_INJECTED:
                return call_next(code, message_id, data_pointer)
            try:
                handled = self._handle_event(
                    event.vkCode,
                    message_id,
                    user32.GetAsyncKeyState,
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

    def _handle_event(self, virtual_key: int, message_id: int, get_async_key_state) -> bool:
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

        if virtual_key == VK_RMENU:
            if is_down:
                if self._right_alt_started is None:
                    self._right_alt_started = time.monotonic()
            elif self._right_alt_started is not None:
                duration_ms = (time.monotonic() - self._right_alt_started) * 1000
                self._right_alt_started = None
                if duration_ms <= MAX_RIGHT_ALT_TAP_MS:
                    self.session.right_alt_tap()
            return True

        physical_key = ACTIVE_VIRTUAL_KEYS.get(virtual_key)
        if physical_key is None:
            return False

        if control or self._is_down(get_async_key_state, VK_LMENU):
            return False
        if is_down:
            self._pressed_active.add(virtual_key)
            output = self.session.handle_physical_key(
                physical_key,
                shifted=self._is_down(get_async_key_state, VK_SHIFT),
            )
            if output:
                self._emit_unicode(output)
            return True
        if virtual_key in self._pressed_active:
            self._pressed_active.discard(virtual_key)
            return True
        return False

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
