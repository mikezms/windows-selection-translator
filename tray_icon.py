"""Windows 系统托盘菜单。"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable

try:
    import win32api
    import win32con
    import win32gui
except ImportError:
    win32api = None
    win32con = None
    win32gui = None

TRAY_AVAILABLE = bool(win32api and win32con and win32gui)

WM_TRAY_NOTIFY = (win32con.WM_USER + 32) if TRAY_AVAILABLE else 0

ID_SHOW = 1001
ID_TOGGLE_ENABLED = 1002
ID_SOURCE_FAST = 1101
ID_SOURCE_GOOGLE = 1102
ID_SOURCE_AI = 1103
ID_SETTINGS = 1201
ID_QUIT = 1301

SOURCE_MENU = (
    (ID_SOURCE_FAST, "mymemory", "通用快速翻译"),
    (ID_SOURCE_GOOGLE, "google", "Google 翻译"),
    (ID_SOURCE_AI, "deepseek", "AI 技术语境翻译"),
)


class WindowsTrayIcon:
    def __init__(
        self,
        *,
        tooltip: str,
        icon_path: str,
        on_show: Callable[[], None],
        on_toggle_enabled: Callable[[], None],
        is_enabled: Callable[[], bool],
        get_source: Callable[[], str],
        set_source: Callable[[str], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self.tooltip = tooltip[:120]
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_toggle_enabled = on_toggle_enabled
        self.is_enabled = is_enabled
        self.get_source = get_source
        self.set_source = set_source
        self.on_settings = on_settings
        self.on_quit = on_quit

        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = False
        self._hwnd = 0
        self._hicon = 0

    def start(self) -> bool:
        if not TRAY_AVAILABLE:
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._ready.clear()
        self._running = False
        self._thread = threading.Thread(target=self._run, name="SnapTranslateTray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1.5)
        return self._running

    def stop(self) -> None:
        if not TRAY_AVAILABLE:
            return
        hwnd = self._hwnd
        if hwnd:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        class_name = f"SnapTranslateTrayWindow{os.getpid()}{id(self)}"
        try:
            hinst = win32api.GetModuleHandle(None)
            wc = win32gui.WNDCLASS()
            wc.hInstance = hinst
            wc.lpszClassName = class_name
            wc.lpfnWndProc = self._wnd_proc
            class_atom = win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindow(
                class_atom,
                self.tooltip,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                hinst,
                None,
            )
            self._hicon = self._load_icon()
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            nid = (self._hwnd, 0, flags, WM_TRAY_NOTIFY, self._hicon, self.tooltip)
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
            self._running = True
            self._ready.set()
            win32gui.PumpMessages()
        except Exception:
            self._running = False
            self._ready.set()
        finally:
            self._hwnd = 0

    def _load_icon(self):
        if self.icon_path and os.path.exists(self.icon_path):
            try:
                return win32gui.LoadImage(
                    0,
                    self.icon_path,
                    win32con.IMAGE_ICON,
                    0,
                    0,
                    win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
                )
            except Exception:
                pass
        return win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY_NOTIFY:
            if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK):
                self._safe_call(self.on_show)
                return 0
            if lparam == win32con.WM_RBUTTONUP:
                self._show_menu(hwnd)
                return 0
        if msg == win32con.WM_COMMAND:
            self._handle_command(wparam & 0xFFFF)
            return 0
        if msg == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            self._remove_icon()
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        menu = win32gui.CreatePopupMenu()
        enabled = self._safe_value(self.is_enabled, False)
        current_source = self._safe_value(self.get_source, "mymemory")
        toggle_label = "暂停快捷键翻译" if enabled else "启用快捷键翻译"

        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_SHOW, "显示主窗口")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_TOGGLE_ENABLED, toggle_label)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, None)
        for item_id, source, label in SOURCE_MENU:
            flags = win32con.MF_STRING
            if source == current_source:
                flags |= win32con.MF_CHECKED
            win32gui.AppendMenu(menu, flags, item_id, label)
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, None)
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_SETTINGS, "API 设置")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_QUIT, "退出")

        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        x, y = win32gui.GetCursorPos()
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON, x, y, 0, hwnd, None)
        win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

    def _handle_command(self, command_id: int) -> None:
        if command_id == ID_SHOW:
            self._safe_call(self.on_show)
        elif command_id == ID_TOGGLE_ENABLED:
            self._safe_call(self.on_toggle_enabled)
        elif command_id == ID_SETTINGS:
            self._safe_call(self.on_settings)
        elif command_id == ID_QUIT:
            self._safe_call(self.on_quit)
        else:
            for item_id, source, _label in SOURCE_MENU:
                if command_id == item_id:
                    self._safe_call(lambda s=source: self.set_source(s))
                    break

    def _remove_icon(self) -> None:
        if self._hwnd:
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self._hwnd, 0))
            except Exception:
                pass
        if self._hicon:
            try:
                win32gui.DestroyIcon(self._hicon)
            except Exception:
                pass
            self._hicon = 0
        self._running = False

    @staticmethod
    def _safe_call(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            pass

    @staticmethod
    def _safe_value(callback: Callable[[], object], default):
        try:
            return callback()
        except Exception:
            return default
