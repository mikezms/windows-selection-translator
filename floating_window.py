"""悬浮翻译窗：显示翻译结果、例句、发音、收录按钮。"""
import re
import threading
import tkinter as tk
from tkinter import font as tkfont, scrolledtext

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

SOURCE_PREVIEW_LENGTH = 360
RESULT_PREVIEW_LENGTH = 1600


def _is_likely_english(text: str) -> bool:
    """纯 ASCII 字母占主导视为英文：至少 3 字母且字母占比 ≥ 50%。"""
    s = (text or "").strip()
    if not s:
        return False
    letters = re.findall(r"[A-Za-z]", s)
    if len(letters) < 3:
        return False
    return len(letters) / len(s) >= 0.5


def _preview_text(text: str, limit: int) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "\n..."


def _looks_like_article(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if len(s) >= 260:
        return True
    if s.count("\n") >= 2:
        return True
    return len(re.findall(r"[.!?。！？]\s+", s)) >= 4


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
        if _looks_like_article(original):
            self._render_article(original, translated)
        else:
            self._render(original, translated, is_message=False)

    def show_message(self, title: str, msg: str, duration_ms: int = 2800) -> None:
        """显示提示/错误消息：无按钮，自动消失。"""
        self._render(title, msg, is_message=True, duration_ms=duration_ms)

    def _render(self, original: str, translated: str, *, is_message: bool, duration_ms: int = 0) -> None:
        self._original = original
        self._translated = translated
        original_view = _preview_text(original, SOURCE_PREVIEW_LENGTH)
        translated_view = _preview_text(translated, RESULT_PREVIEW_LENGTH)

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
            body, text=original_view, justify="left", anchor="w",
            bg=UI_FLOAT_BG, fg=UI_FLOAT_FG, wraplength=460,
            font=tkfont.Font(family=FONT_FAMILY, size=14 if len(original) > SOURCE_PREVIEW_LENGTH else 18, weight="bold"),
        ).pack(fill="x", pady=(0, 4))

        # 译文
        self.meaning_lbl = tk.Label(
            body, text=translated_view, justify="left", anchor="w",
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

    def _render_article(self, original: str, translated: str) -> None:
        self._original = original
        self._translated = translated

        if self.win is not None:
            self.win.destroy()
            self.win = None
            self.save_btn = None

        top = tk.Toplevel(self.root)
        top.title("文章翻译")
        top.configure(bg=UI_FLOAT_BG)
        top.resizable(True, True)
        top.transient(self.root)

        def _close() -> None:
            if self.win is top:
                self.win = None
            self.save_btn = None
            top.destroy()

        top.protocol("WM_DELETE_WINDOW", _close)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1220, max(980, int(screen_w * 0.82)))
        height = min(840, max(700, int(screen_h * 0.8)))
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2)
        top.geometry(f"{width}x{height}+{x}+{y}")

        outer = tk.Frame(top, bg=UI_FLOAT_BG, padx=18, pady=16)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=UI_FLOAT_BG)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(
            header, text="文章翻译", bg=UI_FLOAT_BG, fg=UI_FLOAT_FG,
            font=tkfont.Font(family=FONT_FAMILY, size=18, weight="bold"),
        ).pack(anchor="w")
        tk.Label(
            header, text="自动切换到文章模式。可滚动阅读，也可复制原文或译文。", bg=UI_FLOAT_BG, fg=UI_FLOAT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(anchor="w", pady=(3, 0))

        status_var = tk.StringVar(value="")
        action_row = tk.Frame(header, bg=UI_FLOAT_BG)
        action_row.pack(fill="x", pady=(8, 0))

        def _copy(text: str, label: str) -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            status_var.set(f"已复制{label}")

        tk.Button(
            action_row, text="复制原文", command=lambda: _copy(original, "原文"),
            relief="flat", bd=0, padx=12, pady=6,
            bg="#f1f5f9", fg="#475569",
            activebackground="#e2e8f0", activeforeground="#0f172a",
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"), cursor="hand2",
        ).pack(side="left")
        tk.Button(
            action_row, text="复制译文", command=lambda: _copy(translated, "译文"),
            relief="flat", bd=0, padx=12, pady=6,
            bg=UI_FLOAT_BTN, fg="#ffffff",
            activebackground=UI_FLOAT_BTN_H, activeforeground="#ffffff",
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"), cursor="hand2",
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            action_row, text="关闭", command=top.destroy,
            relief="flat", bd=0, padx=12, pady=6,
            bg=UI_FLOAT_BG_SOFT, fg=UI_FLOAT_MUTED,
            activebackground=UI_FLOAT_BG_SOFT, activeforeground="#ffffff",
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"), cursor="hand2",
        ).pack(side="right")

        tk.Label(
            header, textvariable=status_var, bg=UI_FLOAT_BG, fg=UI_FLOAT_ACCENT,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
        ).pack(anchor="w", pady=(8, 0))

        split = tk.PanedWindow(outer, orient="horizontal", sashwidth=8, sashrelief="flat", bg=UI_FLOAT_BG, bd=0)
        split.pack(fill="both", expand=True)

        left = tk.Frame(split, bg=UI_FLOAT_BG)
        right = tk.Frame(split, bg=UI_FLOAT_BG)
        split.add(left, minsize=360)
        split.add(right, minsize=360)

        self._build_article_panel(left, "原文", original, UI_FLOAT_FG)
        self._build_article_panel(right, "译文", translated, UI_FLOAT_ACCENT)

        self.win = top
        top.lift()
        top.focus_force()

    def _build_article_panel(self, parent: tk.Widget, title: str, text: str, title_color: str) -> None:
        parent.pack_propagate(False)
        parent.configure(bg=UI_FLOAT_BG)
        title_row = tk.Frame(parent, bg=UI_FLOAT_BG)
        title_row.pack(fill="x", pady=(0, 8))
        tk.Label(
            title_row, text=title, bg=UI_FLOAT_BG, fg=title_color,
            font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
        ).pack(anchor="w")

        box = scrolledtext.ScrolledText(
            parent, wrap="word", bg="#ffffff", fg=UI_FLOAT_FG,
            insertbackground=UI_FLOAT_FG, relief="solid", bd=1, highlightthickness=0,
            font=tkfont.Font(family=FONT_FAMILY, size=10),
        )
        box.pack(fill="both", expand=True)
        box.insert("1.0", text)
        box.configure(state="disabled")

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
