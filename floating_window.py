"""悬浮翻译窗：显示翻译结果、例句、发音、收录按钮。"""
import re
import threading
import tkinter as tk
from tkinter import font as tkfont

from bilingual_layout import BilingualPair, build_bilingual_pairs
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
        self._pinned = False

    def show_translation(self, original: str, translated: str) -> None:
        """显示翻译结果卡片：含例句 + 按钮。"""
        if _looks_like_article(original):
            self._render_article(original, translated)
        else:
            self._render(original, translated, is_message=False)

    def show_message(self, title: str, msg: str, duration_ms: int = 2800, actions=None) -> None:
        """显示提示/错误消息：无按钮，自动消失。"""
        self._render(title, msg, is_message=True, duration_ms=duration_ms, actions=actions)

    def _render(
        self,
        original: str,
        translated: str,
        *,
        is_message: bool,
        duration_ms: int = 0,
        actions=None,
    ) -> None:
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

        # 窗口操作
        close_row = tk.Frame(body, bg=UI_FLOAT_BG)
        close_row.pack(fill="x")
        pin_btn = tk.Button(
            close_row, text="固定" if not self._pinned else "已固定",
            command=lambda: self._toggle_pin(top, pin_btn),
            relief="flat", bd=0, padx=8, pady=0,
            bg=UI_FLOAT_BTN if self._pinned else UI_FLOAT_BG,
            fg="#ffffff" if self._pinned else UI_FLOAT_MUTED,
            activebackground=UI_FLOAT_BTN_H if self._pinned else UI_FLOAT_BG_SOFT,
            activeforeground="#ffffff",
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"), cursor="hand2",
        )
        pin_btn.pack(side="right", padx=(0, 6))
        if not self._pinned:
            hover_bind(pin_btn, UI_FLOAT_BG, UI_FLOAT_BG_SOFT, fg=UI_FLOAT_MUTED, hover_fg="#ffffff")
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
            self._build_message_actions(body, top, actions)
            self._finalize_placement(top)
            if duration_ms > 0 and not actions:
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

        # 按钮行
        btn_row = tk.Frame(body, bg=UI_FLOAT_BG)
        btn_row.pack(fill="x")

        copy_original_btn = tk.Button(
            btn_row, text="复制原文", command=lambda: self._copy_to_clipboard(self._original, "原文", copy_original_btn),
            relief="flat", bd=0, pady=8,
            bg="#f1f5f9", fg="#475569",
            activebackground="#e2e8f0", activeforeground="#0f172a",
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"), cursor="hand2",
        )
        copy_original_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        hover_bind(copy_original_btn, "#f1f5f9", "#e2e8f0", fg="#475569", hover_fg="#0f172a")

        speak_btn = tk.Button(
            btn_row, text="♪ 发音", command=self._on_speak_click,
            relief="flat", bd=0, pady=8,
            bg="#f1f5f9", fg="#475569",
            activebackground="#e2e8f0", activeforeground="#0f172a",
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"), cursor="hand2",
        )
        speak_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        hover_bind(speak_btn, "#f1f5f9", "#e2e8f0", fg="#475569", hover_fg="#0f172a")

        copy_btn = tk.Button(
            btn_row, text="复制译文", command=lambda: self._copy_to_clipboard(self._translated, "译文", copy_btn),
            relief="flat", bd=0, pady=8,
            bg="#f1f5f9", fg="#475569",
            activebackground="#e2e8f0", activeforeground="#0f172a",
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"), cursor="hand2",
        )
        copy_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
        hover_bind(copy_btn, "#f1f5f9", "#e2e8f0", fg="#475569", hover_fg="#0f172a")

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

    def _build_message_actions(self, body: tk.Widget, top: tk.Toplevel, actions) -> None:
        if not actions:
            return
        btn_row = tk.Frame(body, bg=UI_FLOAT_BG)
        btn_row.pack(fill="x", pady=(0, 2))
        for idx, (label, command) in enumerate(actions):
            btn = tk.Button(
                btn_row, text=label,
                command=lambda cb=command: self._run_message_action(top, cb),
                relief="flat", bd=0, pady=7,
                bg=UI_FLOAT_BTN if idx == 0 else "#f1f5f9",
                fg="#ffffff" if idx == 0 else "#475569",
                activebackground=UI_FLOAT_BTN_H if idx == 0 else "#e2e8f0",
                activeforeground="#ffffff" if idx == 0 else "#0f172a",
                font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
                cursor="hand2",
            )
            btn.pack(side="left", fill="x", expand=True, padx=(0, 8 if idx + 1 < len(actions) else 0))

    def _run_message_action(self, top: tk.Toplevel, command) -> None:
        if top.winfo_exists():
            top.withdraw()
        if command:
            command()

    def _toggle_pin(self, top: tk.Toplevel, button: tk.Button) -> None:
        self._pinned = not self._pinned
        if top.winfo_exists():
            self._last_pos = (top.winfo_x(), top.winfo_y())
            top.attributes("-topmost", self._pinned)
        button.configure(
            text="已固定" if self._pinned else "固定",
            bg=UI_FLOAT_BTN if self._pinned else UI_FLOAT_BG,
            fg="#ffffff" if self._pinned else UI_FLOAT_MUTED,
            activebackground=UI_FLOAT_BTN_H if self._pinned else UI_FLOAT_BG_SOFT,
        )

    def _render_article(self, original: str, translated: str) -> None:
        self._original = original
        self._translated = translated
        pairs = build_bilingual_pairs(original, translated)

        if self.win is not None:
            self.win.destroy()
            self.win = None
            self.save_btn = None

        top = tk.Toplevel(self.root)
        top.title("文章翻译")
        top.configure(bg=UI_FLOAT_BG)
        top.resizable(True, True)
        top.minsize(680, 560)
        top.transient(self.root)

        def _close() -> None:
            if self.win is top:
                self.win = None
            self.save_btn = None
            top.destroy()

        top.protocol("WM_DELETE_WINDOW", _close)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1080, max(720, int(screen_w * 0.78)))
        height = min(860, max(620, int(screen_h * 0.82)))
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2)
        top.geometry(f"{width}x{height}+{x}+{y}")

        outer = tk.Frame(top, bg=UI_FLOAT_BG, padx=28, pady=22)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=UI_FLOAT_BG)
        header.pack(fill="x", pady=(0, 16))
        title_row = tk.Frame(header, bg=UI_FLOAT_BG)
        title_row.pack(fill="x")
        tk.Label(
            title_row, text="文章对照翻译", bg=UI_FLOAT_BG, fg=UI_FLOAT_FG,
            font=tkfont.Font(family=FONT_FAMILY, size=18, weight="bold"),
        ).pack(side="left")
        tk.Button(
            title_row, text="✕", command=_close,
            relief="flat", bd=0, padx=10, pady=2,
            bg=UI_FLOAT_BG, fg=UI_FLOAT_MUTED,
            activebackground="#f1f5f9", activeforeground=UI_FLOAT_FG,
            font=tkfont.Font(family=FONT_FAMILY, size=12), cursor="hand2",
        ).pack(side="right")
        tk.Label(
            header, text=f"全文翻译结果 · {len(pairs)} 组中英对照", bg=UI_FLOAT_BG, fg=UI_FLOAT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(anchor="w", pady=(3, 0))

        status_var = tk.StringVar(value="")
        action_row = tk.Frame(header, bg=UI_FLOAT_BG)
        action_row.pack(fill="x", pady=(12, 0))

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

        tk.Label(
            action_row, textvariable=status_var, bg=UI_FLOAT_BG, fg=UI_FLOAT_ACCENT,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
        ).pack(side="left", padx=(12, 0))

        self._build_bilingual_reader(outer, top, pairs)

        self.win = top
        top.lift()
        top.focus_force()

    def _build_bilingual_reader(
        self,
        parent: tk.Widget,
        top: tk.Toplevel,
        pairs: list[BilingualPair],
    ) -> None:
        shell = tk.Frame(parent, bg="#f8fafc", highlightbackground="#e2e8f0", highlightthickness=1)
        shell.pack(fill="both", expand=True)

        canvas = tk.Canvas(shell, bg="#f8fafc", highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, bg="#f8fafc")
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        wrapping_labels: list[tk.Label] = []

        for index, pair in enumerate(pairs, start=1):
            block_bg = "#ffffff" if index % 2 else "#f8fafc"
            block = tk.Frame(content, bg=block_bg, padx=26, pady=20)
            block.pack(fill="x")

            meta = tk.Frame(block, bg=block_bg)
            meta.pack(fill="x", pady=(0, 10))
            tk.Label(
                meta, text=f"{index:02d}", bg=block_bg, fg=UI_FLOAT_ACCENT,
                font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            ).pack(side="left")
            tk.Label(
                meta, text=pair.unit, bg=block_bg, fg=UI_FLOAT_MUTED,
                font=tkfont.Font(family=FONT_FAMILY, size=9),
            ).pack(side="left", padx=(8, 0))

            original_label = tk.Label(
                block, text=pair.original, justify="left", anchor="w",
                bg=block_bg, fg=UI_FLOAT_FG,
                font=tkfont.Font(family=FONT_FAMILY, size=11),
            )
            original_label.pack(fill="x")

            translated_row = tk.Frame(block, bg=block_bg)
            translated_row.pack(fill="x", pady=(12, 0))
            tk.Frame(translated_row, bg="#10b981", width=3).pack(side="left", fill="y", padx=(0, 12))
            translated_label = tk.Label(
                translated_row, text=pair.translated, justify="left", anchor="w",
                bg=block_bg, fg="#047857",
                font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
            )
            translated_label.pack(side="left", fill="x", expand=True)
            wrapping_labels.extend((original_label, translated_label))

            if index < len(pairs):
                tk.Frame(content, bg="#e2e8f0", height=1).pack(fill="x")

        def _sync_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _resize_content(event) -> None:
            canvas.itemconfigure(content_window, width=event.width)
            wraplength = max(300, event.width - 92)
            for label in wrapping_labels:
                label.configure(wraplength=wraplength)

        def _scroll(event) -> str:
            if event.delta:
                canvas.yview_scroll(-1 * int(event.delta / 120), "units")
            return "break"

        content.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _resize_content)
        top.bind("<MouseWheel>", _scroll)

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

    def _copy_to_clipboard(self, text: str, label: str, button: tk.Button | None = None) -> None:
        value = (text or "").strip()
        if not value:
            if button is not None:
                button.configure(text="无内容")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        if button is None:
            return
        old_text = str(button.cget("text"))
        button.configure(text=f"已复制{label}")
        self.root.after(
            1200,
            lambda: button.winfo_exists() and button.configure(text=old_text),
        )

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
