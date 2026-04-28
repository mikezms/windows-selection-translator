"""悬浮翻译窗：显示翻译结果、例句、发音、收录按钮。"""
import re
import threading
import tkinter as tk
from tkinter import font as tkfont

import deepseek
import tts
import vocab_store
from hotkey import get_cursor_pos
from ui_theme import (
    FONT_FAMILY,
    UI_FLOAT_ACCENT,
    UI_FLOAT_BG,
    UI_FLOAT_BG_SOFT,
    UI_FLOAT_BTN,
    UI_FLOAT_BTN_H,
    UI_FLOAT_EXAMPLE,
    UI_FLOAT_FG,
    UI_FLOAT_MUTED,
    UI_INFO,
    UI_INFO_HOVER,
    hover_bind,
)


def _is_likely_english(text: str) -> bool:
    """纯 ASCII 字母占主导视为英文：至少 3 字母且字母占比 ≥ 50%。"""
    s = (text or "").strip()
    if not s:
        return False
    letters = re.findall(r"[A-Za-z]", s)
    if len(letters) < 3:
        return False
    return len(letters) / len(s) >= 0.5


class FloatingWindow:
    def __init__(self, root: tk.Tk, vocab_path: str):
        self.root = root
        self.vocab_path = vocab_path
        self.win: tk.Toplevel | None = None
        self.save_btn: tk.Button | None = None
        self._original = ""
        self._translated = ""
        self._last_pos: tuple[int, int] | None = None

    def show_translation(self, original: str, translated: str) -> None:
        """显示翻译结果卡片：含例句 + 按钮。"""
        self._render(original, translated, is_message=False)

    def show_message(self, title: str, msg: str, duration_ms: int = 2800) -> None:
        """显示提示/错误消息：无按钮，自动消失。"""
        self._render(title, msg, is_message=True, duration_ms=duration_ms)

    def _render(self, original: str, translated: str, *, is_message: bool, duration_ms: int = 0) -> None:
        self._original = original
        self._translated = translated

        # 找已有例句（忽略大小写）
        example = ""
        example_zh = ""
        if not is_message:
            it = vocab_store.find_item(vocab_store.load(self.vocab_path), original)
            if it:
                example = it.get("example", "")
                example_zh = it.get("example_zh", "")

        if self.win is not None:
            self.win.destroy()
            self.win = None
            self.save_btn = None

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.97)
        top.configure(bg=UI_FLOAT_BG, highlightbackground=UI_FLOAT_BG_SOFT, highlightthickness=1)

        self._bind_drag(top)

        body = tk.Frame(top, bg=UI_FLOAT_BG, padx=16, pady=14)
        body.pack(fill="both", expand=True)

        # 关闭按钮
        close_row = tk.Frame(body, bg=UI_FLOAT_BG)
        close_row.pack(fill="x")
        close_btn = tk.Button(
            close_row, text="✕", command=lambda: top.withdraw(),
            relief="flat", bd=0, padx=8, pady=0,
            bg=UI_FLOAT_BG, fg=UI_FLOAT_MUTED,
            activebackground=UI_FLOAT_BG_SOFT, activeforeground="#ffffff",
            font=tkfont.Font(family=FONT_FAMILY, size=10), cursor="hand2",
        )
        close_btn.pack(side="right")
        hover_bind(close_btn, UI_FLOAT_BG, UI_FLOAT_BG_SOFT, fg=UI_FLOAT_MUTED, hover_fg="#ffffff")

        # 原文
        tk.Label(
            body, text=original, justify="left", anchor="w",
            bg=UI_FLOAT_BG, fg=UI_FLOAT_FG, wraplength=460,
            font=tkfont.Font(family=FONT_FAMILY, size=18, weight="bold"),
        ).pack(fill="x", pady=(0, 4))

        # 译文
        self.meaning_lbl = tk.Label(
            body, text=translated, justify="left", anchor="w",
            bg=UI_FLOAT_BG, fg=UI_FLOAT_ACCENT, wraplength=460,
            font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
        )
        self.meaning_lbl.pack(fill="x", pady=(0, 16))

        if is_message:
            self._finalize_placement(top)
            if duration_ms > 0:
                top.after(duration_ms, top.withdraw)
            return

        # 例句区块（带单独背景）
        ex_bg = "#f8fafc"
        ex_frame = tk.Frame(body, bg=ex_bg, padx=16, pady=12)
        
        example_lbl = tk.Label(
            ex_frame, text=example or "", justify="left", anchor="w",
            bg=ex_bg, fg=UI_FLOAT_EXAMPLE, wraplength=428,
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"),
        )
        example_zh_lbl = tk.Label(
            ex_frame, text=example_zh or "", justify="left", anchor="w",
            bg=ex_bg, fg=UI_FLOAT_MUTED, wraplength=428,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        )
        need_gen = not example and not example_zh and _is_likely_english(original) and len(original.split()) <= 4
        if example or example_zh:
            ex_frame.pack(fill="x", pady=(0, 16))
            example_lbl.pack(fill="x", pady=(0, 4))
            example_zh_lbl.pack(fill="x")
        elif need_gen:
            ex_frame.pack(fill="x", pady=(0, 16))
            example_lbl.configure(text="⏳ 正在生成例句...", fg=UI_FLOAT_MUTED)
            example_lbl.pack(fill="x")

        # 按钮行：左右各占 50%
        btn_row = tk.Frame(body, bg=UI_FLOAT_BG)
        btn_row.pack(fill="x")

        speak_btn = tk.Button(
            btn_row, text="♪ 发音", command=self._on_speak_click,
            relief="flat", bd=0, pady=8,
            bg="#f1f5f9", fg="#475569",
            activebackground="#e2e8f0", activeforeground="#0f172a",
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"), cursor="hand2",
        )
        speak_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        hover_bind(speak_btn, "#f1f5f9", "#e2e8f0", fg="#475569", hover_fg="#0f172a")

        btn = tk.Button(
            btn_row, text="＋ 收录", command=self._on_save_click,
            relief="flat", bd=0, pady=8,
            bg=UI_FLOAT_BTN, fg="#ffffff",
            activebackground=UI_FLOAT_BTN_H, activeforeground="#ffffff",
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"), cursor="hand2",
        )
        btn.pack(side="left", fill="x", expand=True)
        hover_bind(btn, UI_FLOAT_BTN, UI_FLOAT_BTN_H)

        self.win = top
        self.save_btn = btn
        self._finalize_placement(top)

        # 预缓存发音
        if _is_likely_english(original):
            tts.precache(original)

        # 后台生成例句
        if need_gen:
            self._fetch_example_async(top, ex_frame, example_lbl, example_zh_lbl, original, translated)

    def _bind_drag(self, top: tk.Toplevel) -> None:
        def _start(e):
            top._drag_x = e.x
            top._drag_y = e.y

        def _on(e):
            x = top.winfo_x() + e.x - top._drag_x
            y = top.winfo_y() + e.y - top._drag_y
            top.geometry(f"+{x}+{y}")

        def _end(e):
            self._last_pos = (top.winfo_x(), top.winfo_y())

        top.bind("<Button-1>", _start)
        top.bind("<B1-Motion>", _on)
        top.bind("<ButtonRelease-1>", _end)

    def _finalize_placement(self, top: tk.Toplevel) -> None:
        top.update_idletasks()
        popup_w = max(500, top.winfo_reqwidth())
        popup_h = top.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if self._last_pos is not None:
            x, y = self._last_pos
        else:
            cx, cy = get_cursor_pos()
            x, y = cx + 16, cy + 16
        x = min(max(10, x), max(10, screen_w - popup_w - 10))
        y = min(max(10, y), max(10, screen_h - popup_h - 10))
        top.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
        top.deiconify()
        top.lift()

    def _fetch_example_async(self, top, ex_frame, en_lbl, zh_lbl, word: str, meaning: str) -> None:
        def worker():
            en, zh, refined_meaning = deepseek.generate_example_and_meaning(word, meaning)
            if not top.winfo_exists():
                return
            def update():
                if not top.winfo_exists():
                    return
                # 更新包含词性的详细释义
                if refined_meaning and hasattr(self, 'meaning_lbl'):
                    self.meaning_lbl.configure(text=refined_meaning)
                    self._translated = refined_meaning  # 更新保存到生词本的释义
                
                if en:
                    en_lbl.configure(text=en, fg=UI_FLOAT_EXAMPLE)
                    zh_lbl.configure(text=zh)
                    en_lbl.pack(fill="x", pady=(0, 4))
                    if not zh_lbl.winfo_ismapped():
                        zh_lbl.pack(fill="x")
                    top.update_idletasks()
                    new_h = top.winfo_reqheight()
                    new_w = max(500, top.winfo_reqwidth())
                    top.geometry(f"{new_w}x{new_h}")
                else:
                    ex_frame.pack_forget()
            self.root.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def _on_speak_click(self) -> None:
        text = (self._original or "").strip()
        if text and _is_likely_english(text):
            tts.speak_async(text)

    def _on_save_click(self) -> None:
        word = (self._original or "").strip()
        meaning = (self._translated or "").strip()
        if self.save_btn is not None:
            self.save_btn.configure(state="disabled", text="收录中...")
        threading.Thread(target=self._do_save, args=(word, meaning), daemon=True).start()

    def _do_save(self, word: str, meaning: str) -> None:
        if not word or not meaning:
            self.root.after(0, lambda: self._update_btn("无内容可收录", "#94a3b8"))
            return
        items = vocab_store.load(self.vocab_path)
        if vocab_store.contains(items, word):
            self.root.after(0, lambda: self._update_btn("已在生词本中", "#f59e0b"))
            return
        if not vocab_store.add(items, word, meaning):
            self.root.after(0, lambda: self._update_btn("收录失败", "#dc2626"))
            return
        try:
            vocab_store.save(items, self.vocab_path)
            self.root.after(0, lambda: self._update_btn("收录成功 !", "#059669"))
        except Exception:
            self.root.after(0, lambda: self._update_btn("收录失败", "#dc2626"))

    def _update_btn(self, text: str, color: str) -> None:
        if self.save_btn is not None:
            self.save_btn.configure(text=text, bg=color, state="disabled")
