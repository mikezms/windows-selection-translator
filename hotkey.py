"""Windows 全局热键监听 + 模拟 Ctrl+C 取选中文本。"""
import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable

import pyperclip

MOD_ALT = 0x0001
VK_T = 0x54
HOTKEY_ID = 1
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

COPY_DELAY_SEC = 0.06
CLIPBOARD_STABLE_WAIT = 0.03

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


def copy_selected_text() -> str:
    """模拟 Ctrl+Insert 把选中文本送入剪贴板（避免终端中 Ctrl+C 发送 SIGINT），读出来清洗后返回。"""
    before = pyperclip.paste()
    _user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
    _user32.keybd_event(0x2D, 0, 0, 0)  # Insert down
    _user32.keybd_event(0x2D, 0, 2, 0)  # Insert up
    _user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
    time.sleep(COPY_DELAY_SEC)
    copied = pyperclip.paste()
    if copied == before:
        time.sleep(CLIPBOARD_STABLE_WAIT)
        copied = pyperclip.paste()
    return clean_text(copied)


class HotkeyListener:
    """在独立线程里注册全局热键并派发回调。"""

    def __init__(self, on_hotkey: Callable[[], None]):
        self.on_hotkey = on_hotkey
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self._closing = False
        self._on_fail: Callable[[], None] | None = None

    def start(self, on_register_fail: Callable[[], None] | None = None) -> None:
        self._on_fail = on_register_fail
        self.thread = threading.Thread(target=self._loop, daemon=False)
        self.thread.start()

    def stop(self) -> None:
        self._closing = True
        if self.thread_id:
            _user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        if self.thread is not None:
            self.thread.join(timeout=1.5)

    def _loop(self) -> None:
        self.thread_id = _kernel32.GetCurrentThreadId()
        if not _user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT, VK_T):
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
