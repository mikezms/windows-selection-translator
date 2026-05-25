"""
生词本复习 — 简洁卡片式界面。
词条字段：word, meaning, example, example_zh, score（0–100），reviews。
无例句时自动调 DeepSeek 生成。
"""
from __future__ import annotations

import random
import re
import threading
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox

import app_config
import deepseek
import tts
import vocab_store
from ui_theme import (
    FONT_FAMILY,
    UI_ACCENT,
    UI_ACCENT_DARK,
    UI_ACCENT_HOVER,
    UI_BG,
    UI_BORDER,
    UI_BORDER_SOFT,
    UI_CARD,
    UI_CHIP,
    UI_DANGER,
    UI_DANGER_HOVER,
    UI_INFO,
    UI_INFO_HOVER,
    UI_KEYWORD,
    UI_MEANING,
    UI_OK,
    UI_OK_HOVER,
    UI_TEXT,
    UI_TEXT_MUTED,
    UI_TEXT_SOFT,
    UI_WARN,
    UI_WARN_HOVER,
    UI_ZH,
    hover_bind,
)
from vocab_store import (
    SCORE_MAX,
    SCORE_MIN,
    count_pending_examples,
    item_score,
    needs_bilingual_example,
    normalize_scores,
)

# (档位, 是否已看过): 分数变化
GRADE_DELTA: dict[tuple[str, bool], float] = {
    ("know", False): 10.0,
    ("vague", False): -4.0,
    ("unknown", False): -8.0,
    ("know", True): 5.0,
    ("vague", True): -7.0,
    ("unknown", True): -12.0,
}


class VocabReviewApp:
    def __init__(self) -> None:
        self.vocab_path = vocab_store.DEFAULT_VOCAB_PATH
        self.vocab: list[dict] = vocab_store.load(self.vocab_path)
        normalize_scores(self.vocab)
        self.order: list[int] = []
        self.pos = 0
        self.reveal_meaning = True
        self._gen_running = False

        self.root = tk.Tk()
        self.root.title("SnapTranslate — 生词本")
        self.root.geometry("640x580")
        self.root.minsize(520, 480)
        self.root.configure(bg=UI_BG)

        self.sort_mode_var = tk.StringVar(master=self.root, value="随机")
        self.word_var = tk.StringVar(master=self.root, value="")
        self.meaning_var = tk.StringVar(master=self.root, value="")
        self.progress_var = tk.StringVar(master=self.root, value="0 / 0")
        self.score_var = tk.StringVar(master=self.root, value="")

        self._build_ui()
        self._rebuild_order()
        self._show_card()

    # ---- UI ----

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=UI_BG, padx=22, pady=18)
        outer.pack(fill="both", expand=True)

        # === 顶部工具栏 ===
        toolbar = tk.Frame(outer, bg=UI_BG)
        toolbar.pack(fill="x", pady=(0, 14))

        # 左侧：排序 + 批量生成
        left = tk.Frame(toolbar, bg=UI_BG)
        left.pack(side="left")
        tk.Label(
            left, text="排序", bg=UI_BG, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(side="left")
        sort_menu = tk.OptionMenu(
            left, self.sort_mode_var, "随机", "低分优先", "高分优先",
            command=lambda _: self._on_sort_mode_change(),
        )
        sort_menu.configure(
            bg=UI_CARD, fg=UI_TEXT_SOFT,
            activebackground=UI_CHIP, activeforeground=UI_ACCENT,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            relief="flat", bd=0, highlightthickness=1, highlightbackground=UI_BORDER,
        )
        sort_menu["menu"].configure(bg=UI_CARD, fg=UI_TEXT_SOFT, activebackground=UI_CHIP, activeforeground=UI_ACCENT)
        sort_menu.pack(side="left", padx=(6, 12))

        empty_n = count_pending_examples(self.vocab)
        self.gen_btn = tk.Button(
            left, text=f"⚡  生成例句（{empty_n}）",
            command=self._start_generate_examples,
            bg=UI_ACCENT, fg="#ffffff",
            activebackground=UI_ACCENT_DARK, activeforeground="#ffffff",
            relief="flat", padx=14, pady=6,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            cursor="hand2",
        )
        self.gen_btn.pack(side="left")
        hover_bind(self.gen_btn, UI_ACCENT, UI_ACCENT_HOVER)

        # 右侧：进度
        tk.Label(
            toolbar, textvariable=self.progress_var, bg=UI_BG, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(side="right")

        # === 卡片区域 ===
        card = tk.Frame(
            outer, bg=UI_CARD,
            highlightbackground=UI_BORDER, highlightthickness=1,
            padx=26, pady=20,
        )
        card.pack(fill="both", expand=True, pady=(0, 14))

        # 导航行（左 < 、中 熟练度，右 >）
        nav_row = tk.Frame(card, bg=UI_CARD)
        nav_row.pack(fill="x", pady=(0, 14))
        nav_kw = dict(
            relief="flat", bd=0, padx=14, pady=6,
            bg=UI_CHIP, fg=UI_ACCENT,
            activebackground=UI_ACCENT, activeforeground="#ffffff",
            font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
            cursor="hand2",
        )
        btn_prev = tk.Button(nav_row, text="←", command=self._prev_card, **nav_kw)
        btn_prev.pack(side="left")
        hover_bind(btn_prev, UI_CHIP, UI_ACCENT, fg=UI_ACCENT, hover_fg="#ffffff")

        tk.Label(
            nav_row, textvariable=self.score_var, bg=UI_CARD, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(side="left", fill="x", expand=True)

        btn_next = tk.Button(nav_row, text="→", command=self._next_card, **nav_kw)
        btn_next.pack(side="right")
        hover_bind(btn_next, UI_CHIP, UI_ACCENT, fg=UI_ACCENT, hover_fg="#ffffff")

        # 单词行
        word_row = tk.Frame(card, bg=UI_CARD)
        word_row.pack(pady=(8, 8))
        tk.Label(
            word_row, textvariable=self.word_var, bg=UI_CARD, fg=UI_TEXT,
            font=tkfont.Font(family=FONT_FAMILY, size=26, weight="bold"),
        ).pack(side="left")
        btn_speak = tk.Button(
            word_row, text="♪", command=self._speak_word,
            relief="flat", bd=0, padx=10, pady=4,
            bg=UI_CARD, fg=UI_INFO,
            activebackground=UI_CARD, activeforeground=UI_INFO_HOVER,
            font=tkfont.Font(family=FONT_FAMILY, size=18), cursor="hand2",
        )
        btn_speak.pack(side="left", padx=(10, 0))
        hover_bind(btn_speak, UI_CARD, UI_CHIP)

        # 释义
        tk.Label(
            card, textvariable=self.meaning_var, bg=UI_CARD, fg=UI_MEANING,
            font=tkfont.Font(family=FONT_FAMILY, size=14),
            wraplength=520, justify="center",
        ).pack(pady=(0, 16))

        # 分隔线
        tk.Frame(card, bg=UI_BORDER_SOFT, height=1).pack(fill="x", pady=(0, 12))

        # 例句区域
        self._font_example = tkfont.Font(family=FONT_FAMILY, size=10)
        self._font_example_bold = tkfont.Font(family=FONT_FAMILY, size=10, weight="bold")
        ex_bg = "#fafbfc"
        ex_wrap = tk.Frame(
            card, bg=ex_bg,
            highlightbackground=UI_BORDER_SOFT, highlightthickness=1,
        )
        ex_wrap.pack(fill="both", expand=True)

        ex_header = tk.Frame(ex_wrap, bg=ex_bg)
        ex_header.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(
            ex_header, text="📝  例句", bg=ex_bg, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
        ).pack(side="left")
        btn_ex_speak = tk.Button(
            ex_header, text="♪ 朗读", command=self._speak_example,
            relief="flat", bd=0, padx=12, pady=4,
            bg=UI_INFO, fg="#ffffff",
            activebackground=UI_INFO_HOVER, activeforeground="#ffffff",
            font=tkfont.Font(family=FONT_FAMILY, size=8, weight="bold"),
            cursor="hand2",
        )
        btn_ex_speak.pack(side="right")
        hover_bind(btn_ex_speak, UI_INFO, UI_INFO_HOVER)

        self.example_text = tk.Text(
            ex_wrap, wrap="word", state="disabled",
            bg=ex_bg, fg=UI_KEYWORD, relief="flat",
            padx=14, pady=10, cursor="arrow",
            font=self._font_example, highlightthickness=0,
            spacing1=2, spacing3=2,
        )
        self.example_text.tag_configure("keyword", font=self._font_example_bold, foreground=UI_KEYWORD)
        self.example_text.tag_configure("zh_line", foreground=UI_ZH)
        self.example_text.tag_configure("muted", foreground=UI_TEXT_MUTED)
        self.example_text.tag_configure("loading", foreground="#94a3b8")
        self.example_text.pack(fill="both", expand=True)

        # === 底部评分按钮 ===
        grade_fr = tk.Frame(outer, bg=UI_BG)
        grade_fr.pack(fill="x")
        btn_kw = dict(
            relief="flat", pady=12, cursor="hand2",
            font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
            bd=0, highlightthickness=0,
        )
        btn_know = tk.Button(
            grade_fr, text="✓  认识", command=lambda: self._apply_grade("know"),
            bg=UI_OK, fg="#ffffff",
            activebackground=UI_OK_HOVER, activeforeground="#ffffff", **btn_kw,
        )
        btn_know.pack(side="left", expand=True, fill="x", padx=(0, 6))
        hover_bind(btn_know, UI_OK, UI_OK_HOVER)

        btn_vague = tk.Button(
            grade_fr, text="？  模糊", command=lambda: self._apply_grade("vague"),
            bg=UI_WARN, fg="#ffffff",
            activebackground=UI_WARN_HOVER, activeforeground="#ffffff", **btn_kw,
        )
        btn_vague.pack(side="left", expand=True, fill="x", padx=(0, 6))
        hover_bind(btn_vague, UI_WARN, UI_WARN_HOVER)

        btn_unknown = tk.Button(
            grade_fr, text="✕  不认识", command=lambda: self._apply_grade("unknown"),
            bg=UI_DANGER, fg="#ffffff",
            activebackground=UI_DANGER_HOVER, activeforeground="#ffffff", **btn_kw,
        )
        btn_unknown.pack(side="left", expand=True, fill="x")
        hover_bind(btn_unknown, UI_DANGER, UI_DANGER_HOVER)

    # ---- 排序 / 导航 ----

    def _on_sort_mode_change(self) -> None:
        self._rebuild_order()
        self.pos = 0
        self._show_card()

    def _rebuild_order(self) -> None:
        n = len(self.vocab)
        self.order = list(range(n))
        if n <= 1:
            return
        mode = self.sort_mode_var.get()
        if mode == "随机":
            random.shuffle(self.order)
        elif mode == "低分优先":
            self.order.sort(key=lambda i: (item_score(self.vocab[i]), i))
        elif mode == "高分优先":
            self.order.sort(key=lambda i: (-item_score(self.vocab[i]), i))

    def _current_item(self) -> dict | None:
        if not self.order or self.pos < 0 or self.pos >= len(self.order):
            return None
        idx = self.order[self.pos]
        if idx < 0 or idx >= len(self.vocab):
            return None
        return self.vocab[idx]

    def _prev_card(self) -> None:
        if not self.order:
            return
        self.pos = (self.pos - 1) % len(self.order)
        self._show_card()

    def _next_card(self) -> None:
        if not self.order:
            return
        self.pos = (self.pos + 1) % len(self.order)
        self._show_card()

    # ---- 发音 ----

    def _speak_word(self) -> None:
        it = self._current_item()
        if it:
            word = str(it.get("word", "")).strip()
            if word:
                tts.speak_async(word)

    def _speak_example(self) -> None:
        it = self._current_item()
        if it:
            ex = str(it.get("example", "") or "").strip()
            if ex:
                tts.speak_async(ex)

    # ---- 卡片显示 ----

    def _show_card(self) -> None:
        n = len(self.vocab)
        if n == 0:
            self.progress_var.set("0 / 0")
            self.score_var.set("")
            self.word_var.set("（词表为空）")
            self.meaning_var.set("")
            self._clear_example()
            return

        self.progress_var.set(f"{self.pos + 1} / {len(self.order)}")
        it = self._current_item()
        if not it:
            return
        sc = item_score(it)
        rev = int(it.get("reviews") or 0)
        self.score_var.set(f"熟练度 {sc:.0f} / 100   已评 {rev} 次")
        self.word_var.set(str(it.get("word", "")))
        self.meaning_var.set(str(it.get("meaning", "")))
        self.reveal_meaning = True
        self._render_example(it)

        # 预缓存发音
        word = str(it.get("word", "")).strip()
        ex = str(it.get("example", "") or "").strip()
        if word:
            tts.precache(word)
        if ex:
            tts.precache(ex)

        # 无例句 → 自动生成
        if needs_bilingual_example(it):
            self._auto_generate_example(it)

    def _clear_example(self) -> None:
        self.example_text.configure(state="normal")
        self.example_text.delete("1.0", "end")
        self.example_text.configure(state="disabled")

    def _render_example(self, it: dict) -> None:
        word_kw = str(it.get("word", "")).strip()
        exs = str(it.get("example", "") or "").strip()
        zhs = str(it.get("example_zh", "") or "").strip()

        self.example_text.configure(state="normal")
        self.example_text.delete("1.0", "end")
        if not exs and not zhs:
            self.example_text.insert("end", "正在生成例句...", ("loading",))
        else:
            if exs:
                self._insert_bold_keyword(self.example_text, exs, word_kw)
            self.example_text.insert("end", "\n\n")
            if zhs:
                self.example_text.insert("end", zhs, ("zh_line",))
        self.example_text.configure(state="disabled")

    @staticmethod
    def _insert_bold_keyword(widget: tk.Text, body: str, keyword: str) -> None:
        keyword = (keyword or "").strip()
        if not keyword:
            widget.insert("end", body)
            return
        pattern = re.escape(keyword)
        try:
            parts = re.split(f"({pattern})", body, flags=re.IGNORECASE)
        except re.error:
            widget.insert("end", body)
            return
        kw_lower = keyword.lower()
        for part in parts:
            if not part:
                continue
            if part.lower() == kw_lower:
                widget.insert("end", part, ("keyword",))
            else:
                widget.insert("end", part)

    # ---- 自动生成例句 ----

    def _auto_generate_example(self, it: dict) -> None:
        word = str(it.get("word", ""))
        meaning = str(it.get("meaning", ""))

        def _worker():
            en, zh = deepseek.generate_example(word, meaning)
            if not en:
                return
            it["example"] = en
            it["example_zh"] = zh
            try:
                vocab_store.save(self.vocab, self.vocab_path)
            except Exception:
                return
            if self.root.winfo_exists() and self._current_item() is it:
                self.root.after(0, lambda: self._render_example(it))

        threading.Thread(target=_worker, daemon=True).start()

    # ---- 评分 ----

    def _apply_grade(self, grade: str) -> None:
        it = self._current_item()
        if not it:
            return
        revealed = bool(self.reveal_meaning)
        delta = GRADE_DELTA.get((grade, revealed))
        if delta is None:
            return
        old = item_score(it)
        new = max(SCORE_MIN, min(SCORE_MAX, old + delta))
        it["score"] = round(new, 1)
        it["reviews"] = int(it.get("reviews") or 0) + 1
        try:
            vocab_store.save(self.vocab, self.vocab_path)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))
            return
        self._advance_after_grade()

    def _advance_after_grade(self) -> None:
        if not self.order:
            return
        n = len(self.order)
        cur_idx = self.order[self.pos]
        self._rebuild_order()
        try:
            new_pos = self.order.index(cur_idx)
        except ValueError:
            new_pos = 0
        self.pos = (new_pos + 1) % n
        self._show_card()

    # ---- 批量生成 ----

    def _refresh_gen_button_label(self) -> None:
        empty_n = count_pending_examples(self.vocab)
        self.gen_btn.configure(text=f"⚡  生成例句（{empty_n}）")

    def _start_generate_examples(self) -> None:
        if self._gen_running:
            return
        if not app_config.is_ai_configured():
            messagebox.showwarning("提示", "请先在主程序的 API 设置中填写服务商、模型和 API Key。")
            return
        pending = [(i, it) for i, it in enumerate(self.vocab) if needs_bilingual_example(it)]
        if not pending:
            messagebox.showinfo("提示", "所有词条都已有例句。")
            return
        self._gen_running = True
        self.gen_btn.configure(state="disabled", text="生成中...")

        def worker() -> None:
            total = len(pending)
            ok = 0
            for n, (idx, it) in enumerate(pending, start=1):
                if not self.root.winfo_exists():
                    break
                word = str(it.get("word", ""))
                meaning = str(it.get("meaning", ""))
                en, zh = deepseek.generate_example(word, meaning)
                if en and zh:
                    it["example"] = en
                    it["example_zh"] = zh
                    try:
                        vocab_store.save(self.vocab, self.vocab_path)
                        ok += 1
                    except Exception:
                        pass
                time.sleep(0.35)
            self.root.after(0, lambda o=ok, t=total: self._gen_finished(o, t))

        threading.Thread(target=worker, daemon=True).start()

    def _gen_finished(self, ok: int, total: int) -> None:
        self._gen_running = False
        self._refresh_gen_button_label()
        self.gen_btn.configure(state="normal")
        self._show_card()
        messagebox.showinfo("完成", f"例句生成完毕：成功 {ok} / {total}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    VocabReviewApp().run()


if __name__ == "__main__":
    main()
