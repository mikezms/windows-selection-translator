"""Windows 全局热键监听 + 模拟 Ctrl+C 取选中文本。"""
import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable

import pyperclip

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_C = 0x43
VK_INSERT = 0x2D
VK_T = 0x54
HOTKEY_ID = 1
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

KEY_RELEASE_WAIT_SEC = 0.35
COPY_RETRY_INTERVAL_SEC = 0.03
COPY_TIMEOUT_SEC = 0.45

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def clean_text(raw: str) -> str:
    text = (raw or "").strip().replace("\r", " ").replace("\n", " ")
    while "  " in text:
        text = text.replace("  ", " ")
    return text


def get_cursor_pos() -> tuple[int, int]:
    p = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def _is_key_down(vk: int) -> bool:
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def parse_hotkey(value: str) -> tuple[int, int]:
    raw = str(value or "").strip().lower().replace("＋", "+").replace(" ", "")
    if not raw:
        return MOD_ALT, VK_T
    parts = [part for part in raw.split("+") if part]
    if not parts:
        return MOD_ALT, VK_T

    mods = 0
    key_name = parts[-1]
    for part in parts[:-1]:
        if part in {"alt", "menu"}:
            mods |= MOD_ALT
        elif part in {"ctrl", "control"}:
            mods |= MOD_CONTROL
        elif part in {"shift"}:
            mods |= MOD_SHIFT
        elif part in {"win", "super"}:
            mods |= MOD_WIN

    key_map = {
        "t": VK_T,
        "c": VK_C,
        "insert": VK_INSERT,
        "tab": 0x09,
        "space": 0x20,
        "f1": 0x70,
        "f2": 0x71,
        "f3": 0x72,
        "f4": 0x73,
        "f5": 0x74,
        "f6": 0x75,
        "f7": 0x76,
        "f8": 0x77,
        "f9": 0x78,
        "f10": 0x79,
        "f11": 0x7A,
        "f12": 0x7B,
    }
    if len(key_name) == 1:
        key = ord(key_name.upper())
    else:
        key = key_map.get(key_name, VK_T)
    return mods or MOD_ALT, key


def _wait_hotkey_released() -> None:
    deadline = time.time() + KEY_RELEASE_WAIT_SEC
    while time.time() < deadline:
        if (
            not _is_key_down(VK_MENU)
            and not _is_key_down(VK_CONTROL)
            and not _is_key_down(VK_SHIFT)
            and not _is_key_down(VK_LWIN)
            and not _is_key_down(VK_RWIN)
        ):
            return
        time.sleep(0.01)


def _send_copy_shortcut(use_insert: bool = False) -> None:
    copy_key = VK_INSERT if use_insert else VK_C
    _user32.keybd_event(VK_CONTROL, 0, 0, 0)
    _user32.keybd_event(copy_key, 0, 0, 0)
    _user32.keybd_event(copy_key, 0, 2, 0)
    _user32.keybd_event(VK_CONTROL, 0, 2, 0)


def _clipboard_text() -> str:
    try:
        return pyperclip.paste()
    except Exception:
        return ""


def _set_clipboard_text(text: str) -> bool:
    for _ in range(3):
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            time.sleep(0.02)
    return False


def _wait_for_clipboard_text(sentinel: str) -> str:
    deadline = time.time() + COPY_TIMEOUT_SEC
    while time.time() < deadline:
        copied = _clipboard_text()
        if copied != sentinel:
            return copied
        time.sleep(COPY_RETRY_INTERVAL_SEC)
    return ""


def copy_selected_text() -> str:
    """模拟复制选中文本；复制失败时返回空，避免误用旧剪贴板内容。"""
    _wait_hotkey_released()

    before = _clipboard_text()
    sentinel = f"__SNAPTRANSLATE_COPY_SENTINEL_{time.time_ns()}__"
    if not _set_clipboard_text(sentinel):
        return ""

    _send_copy_shortcut(use_insert=False)
    copied = _wait_for_clipboard_text(sentinel)

    if not copied:
        _send_copy_shortcut(use_insert=True)
        copied = _wait_for_clipboard_text(sentinel)

    if not copied:
        _set_clipboard_text(before)
        return ""
    return clean_text(copied)


class HotkeyListener:
    """在独立线程里注册全局热键并派发回调。"""

    def __init__(self, on_hotkey: Callable[[], None], hotkey: str = "alt+t"):
        self.on_hotkey = on_hotkey
        self.hotkey = hotkey
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self._closing = False
        self._on_fail: Callable[[], None] | None = None

    def start(self, on_register_fail: Callable[[], None] | None = None) -> None:
        self._closing = False
        self._on_fail = on_register_fail
        self.thread = threading.Thread(target=self._loop, daemon=False)
        self.thread.start()

    def set_hotkey(self, hotkey: str) -> None:
        self.hotkey = hotkey

    def stop(self) -> None:
        self._closing = True
        if self.thread_id:
            _user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread is not None:
            self.thread.join(timeout=1.5)

    def _loop(self) -> None:
        self.thread_id = _kernel32.GetCurrentThreadId()
        mods, key = parse_hotkey(self.hotkey)
        if not _user32.RegisterHotKey(None, HOTKEY_ID, mods, key):
            if self._on_fail:
                self._on_fail()
            return

        msg = wintypes.MSG()
        try:
            while not self._closing:
                ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    threading.Thread(target=self.on_hotkey, daemon=True).start()
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _user32.UnregisterHotKey(None, HOTKEY_ID)
