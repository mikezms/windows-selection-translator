import os
import sys
import threading
import time
import random
import tkinter as tk
from tkinter import font as tkfont, scrolledtext, messagebox

import hotkey as hk
import translator
import deepseek
import tts
import vocab_store
from floating_window import FloatingWindow
from ui_theme import (
    FONT_FAMILY, UI_ACCENT, UI_ACCENT_DARK, UI_ACCENT_HOVER, UI_BG, UI_BG_ALT,
    UI_BORDER, UI_BORDER_SOFT, UI_CARD, UI_CHIP, UI_LOG_BG, UI_STATUS_BG,
    UI_TEXT, UI_TEXT_MUTED, UI_TEXT_SOFT, UI_MEANING, UI_KEYWORD, UI_ZH, UI_INFO, UI_INFO_HOVER,
    UI_OK, UI_OK_HOVER, UI_WARN, UI_WARN_HOVER, UI_DANGER, UI_DANGER_HOVER,
    hover_bind
)
from vocab_store import (
    SCORE_MAX, SCORE_MIN, count_pending_examples, item_score,
    needs_bilingual_example, normalize_scores
)
from vocab_review import GRADE_DELTA

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VOCAB_PATH = os.path.join(SCRIPT_DIR, "vocab.json")
MAX_TEXT_LENGTH = 120

class UnifiedApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LingoLens - 全域词典")
        self.root.geometry("860x640")
        self.root.minsize(700, 500)
        self.root.configure(bg=UI_BG)

        # 全局状态
        self.status_var = tk.StringVar(value="就绪")
        self.enable_var = tk.BooleanVar(value=True)
        self.floating_var = tk.BooleanVar(value=True)
        self.translate_source_var = tk.StringVar(value="mymemory")
        
        self._enabled_lock = threading.Lock()
        self._translate_enabled = True

        # 生词本状态
        self.vocab = vocab_store.load(VOCAB_PATH)
        normalize_scores(self.vocab)
        self.sort_mode_var = tk.StringVar(value="最新添加")
        
        # 悬浮窗和快捷键
        self.floating = None
        self.hotkey_listener = hk.HotkeyListener(on_hotkey=self._do_translate_job)

        self._build_ui()
        self._load_vocab_list()

    # ---- 翻译业务逻辑 ----
    def _is_translate_enabled(self):
        with self._enabled_lock:
            return self._translate_enabled

    def _on_enable_toggle(self):
        with self._enabled_lock:
            self._translate_enabled = bool(self.enable_var.get())
        if self._translate_enabled:
            self.status_var.set("已开启 — 划词后按 Ctrl + L 即可翻译")
        else:
            self.status_var.set("已暂停 — 不会响应快捷键")

    def _append_log(self, original, result):
        ts = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] 原文：{original}\n", "orig")
        self.log_text.insert("end", f"     译文：{result}\n\n", "trans")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _do_translate_job(self):
        if not self._is_translate_enabled(): return
        text = hk.copy_selected_text()
        if not text:
            self.root.after(0, lambda: self._show_error("提示", "未检测到选中文本，请先划词再按 Ctrl + L"))
            return
        if len(text) > MAX_TEXT_LENGTH: text = text[:MAX_TEXT_LENGTH] + "..."
        try:
            src = self.translate_source_var.get()
            translated = translator.translate(text, src)
            self.root.after(0, lambda t=text, tr=translated: self._show_result(t, tr))
        except Exception as exc:
            self.root.after(0, lambda t=text, e=exc: self._show_error(t, f"翻译失败: {e}"))

    def _show_result(self, original, translated):
        self._append_log(original, translated)
        if self.floating and self.floating_var.get():
            self.floating.show_translation(original, translated)

    def _show_error(self, title, msg):
        self._append_log(title, msg)
        if self.floating and self.floating_var.get():
            self.floating.show_message(title, msg, duration_ms=2800)

    # ---- 界面构建 (Dashboard UX) ----
    def _build_ui(self):
        # 整体分左右
        self.sidebar = tk.Frame(self.root, bg=UI_BG_ALT, width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False) # 固定宽度

        self.main_area = tk.Frame(self.root, bg=UI_BG)
        self.main_area.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_history_tab()
        self._build_vocab_tab()

        # 默认显示历史
        self._switch_tab('history')

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_sidebar(self):
        # 品牌
        brand = tk.Frame(self.sidebar, bg=UI_BG_ALT, pady=24, padx=16)
        brand.pack(fill="x")
        tk.Label(brand, text="⚡ LingoLens", bg=UI_BG_ALT, fg=UI_ACCENT, font=tkfont.Font(family=FONT_FAMILY, size=16, weight="bold")).pack(anchor="w")

        # 导航
        nav = tk.Frame(self.sidebar, bg=UI_BG_ALT, padx=12)
        nav.pack(fill="x", pady=10)

        self.nav_btns = {}
        def _make_nav(id, text, icon=""):
            btn = tk.Button(nav, text=f"{icon}  {text}", anchor="w", padx=16, pady=10, relief="flat", bd=0, 
                            bg=UI_BG_ALT, fg=UI_TEXT_SOFT, activebackground=UI_CHIP, activeforeground=UI_ACCENT,
                            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"), cursor="hand2")
            btn.pack(fill="x", pady=2)
            btn.configure(command=lambda: self._switch_tab(id))
            hover_bind(btn, UI_BG_ALT, UI_CHIP, fg=UI_TEXT_SOFT, hover_fg=UI_ACCENT)
            self.nav_btns[id] = btn

        _make_nav('history', '翻译历史', '🕒')
        _make_nav('vocab', '生词复习', '📖')

        # 底部设置 (Dashboard 特色：设置直接展示在侧边栏底部)
        settings = tk.Frame(self.sidebar, bg=UI_CARD, highlightthickness=1, highlightbackground=UI_BORDER, padx=12, pady=16)
        settings.pack(side="bottom", fill="x", padx=12, pady=24)

        tk.Label(settings, text="快速控制", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 10))
        
        chk_kw = dict(bg=UI_CARD, fg=UI_TEXT_SOFT, activebackground=UI_CARD, activeforeground=UI_TEXT,
                      selectcolor=UI_CHIP, font=tkfont.Font(family=FONT_FAMILY, size=9), highlightthickness=0, bd=0)
        
        tk.Checkbutton(settings, text="划词翻译 (Ctrl+L)", variable=self.enable_var, command=self._on_enable_toggle, **chk_kw).pack(anchor="w", pady=2)
        tk.Checkbutton(settings, text="鼠标悬浮提示", variable=self.floating_var, **chk_kw).pack(anchor="w", pady=2)

        tk.Frame(settings, bg=UI_BORDER_SOFT, height=1).pack(fill="x", pady=10)
        tk.Label(settings, text="翻译引擎", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 6))
        
        rb_kw = dict(bg=UI_CARD, activebackground=UI_CARD, fg=UI_TEXT_SOFT, selectcolor=UI_CHIP,
                     font=tkfont.Font(family=FONT_FAMILY, size=9), highlightthickness=0, bd=0)
        tk.Radiobutton(settings, text="MyMemory (免代理)", variable=self.translate_source_var, value="mymemory", **rb_kw).pack(anchor="w")
        tk.Radiobutton(settings, text="Google Translate", variable=self.translate_source_var, value="google", **rb_kw).pack(anchor="w")

    def _switch_tab(self, tab_id):
        # 更新按钮样式
        for tid, btn in self.nav_btns.items():
            if tid == tab_id:
                btn.configure(bg=UI_CHIP, fg=UI_ACCENT)
                btn.unbind("<Enter>")
                btn.unbind("<Leave>")
            else:
                btn.configure(bg=UI_BG_ALT, fg=UI_TEXT_SOFT)
                hover_bind(btn, UI_BG_ALT, UI_CHIP, fg=UI_TEXT_SOFT, hover_fg=UI_ACCENT)
        
        # 切换显示
        if tab_id == 'history':
            self.vocab_frame.pack_forget()
            self.history_frame.pack(fill="both", expand=True)
            self._load_vocab_list() # 切回来时如果有生词收录，更新一下
        elif tab_id == 'vocab':
            self.history_frame.pack_forget()
            self.vocab_frame.pack(fill="both", expand=True)

    # ---- 翻译历史 Tab ----
    def _build_history_tab(self):
        self.history_frame = tk.Frame(self.main_area, bg=UI_BG, padx=24, pady=24)
        
        header = tk.Frame(self.history_frame, bg=UI_BG)
        header.pack(fill="x", pady=(0, 20))
        tk.Label(header, text="最近翻译记录", bg=UI_BG, fg=UI_TEXT, font=tkfont.Font(family=FONT_FAMILY, size=16, weight="bold")).pack(side="left")
        
        btn_clear = tk.Button(header, text="🗑 清空", command=self._clear_log,
                              bg=UI_BG, fg=UI_TEXT_MUTED, activebackground=UI_CHIP, activeforeground=UI_DANGER,
                              relief="flat", bd=0, font=tkfont.Font(family=FONT_FAMILY, size=9), cursor="hand2")
        btn_clear.pack(side="right")

        card = tk.Frame(self.history_frame, bg=UI_CARD, highlightbackground=UI_BORDER, highlightthickness=1, padx=2, pady=2)
        card.pack(fill="both", expand=True)
        
        self.log_text = scrolledtext.ScrolledText(
            card, wrap="word", state="disabled", font=tkfont.Font(family=FONT_FAMILY, size=11),
            bg=UI_LOG_BG, fg=UI_TEXT, insertbackground=UI_TEXT, relief="flat", bd=0, padx=16, pady=16, highlightthickness=0,
            spacing1=6, spacing3=6
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("orig", foreground=UI_TEXT_SOFT, font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"))
        self.log_text.tag_configure("trans", foreground=UI_ACCENT)

        # 状态提示
        status = tk.Frame(self.history_frame, bg=UI_STATUS_BG, padx=12, pady=10, highlightthickness=0)
        status.pack(fill="x", pady=(16, 0))
        tk.Label(status, text="●", bg=UI_STATUS_BG, fg=UI_ACCENT, font=tkfont.Font(family=FONT_FAMILY, size=8)).pack(side="left", padx=(0, 6))
        tk.Label(status, textvariable=self.status_var, bg=UI_STATUS_BG, fg=UI_TEXT_SOFT, font=tkfont.Font(family=FONT_FAMILY, size=9)).pack(side="left")


    # ---- 生词本 Tab (Master-Detail UX) ----
    def _build_vocab_tab(self):
        self.vocab_frame = tk.Frame(self.main_area, bg=UI_BG, padx=24, pady=24)
        
        header = tk.Frame(self.vocab_frame, bg=UI_BG)
        header.pack(fill="x", pady=(0, 16))
        tk.Label(header, text="生词本", bg=UI_BG, fg=UI_TEXT, font=tkfont.Font(family=FONT_FAMILY, size=16, weight="bold")).pack(side="left")

        # Master-Detail Split
        split = tk.PanedWindow(self.vocab_frame, orient="horizontal", bg=UI_BORDER, sashwidth=2)
        split.pack(fill="both", expand=True)

        # Left: Master List
        left_fr = tk.Frame(split, bg=UI_CARD, highlightthickness=1, highlightbackground=UI_BORDER)
        split.add(left_fr, minsize=180, stretch="never", width=220)

        left_top = tk.Frame(left_fr, bg=UI_CARD, padx=8, pady=8)
        left_top.pack(fill="x")
        sort_menu = tk.OptionMenu(left_top, self.sort_mode_var, "最新添加", "低分优先", "高分优先", "A-Z", command=lambda _: self._load_vocab_list())
        sort_menu.configure(bg=UI_BG_ALT, fg=UI_TEXT_SOFT, activebackground=UI_CHIP, activeforeground=UI_ACCENT, relief="flat", bd=0, highlightthickness=0, font=tkfont.Font(family=FONT_FAMILY, size=9))
        sort_menu["menu"].configure(bg=UI_CARD, fg=UI_TEXT_SOFT, activebackground=UI_CHIP, activeforeground=UI_ACCENT)
        sort_menu.pack(fill="x")

        # 使用 Listbox 实现极简列表
        list_frame = tk.Frame(left_fr, bg=UI_CARD)
        list_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self.vocab_listbox = tk.Listbox(
            list_frame, yscrollcommand=scrollbar.set, bg=UI_CARD, fg=UI_TEXT,
            selectbackground=UI_CHIP, selectforeground=UI_ACCENT, relief="flat", bd=0, highlightthickness=0,
            font=tkfont.Font(family=FONT_FAMILY, size=11), activestyle="none"
        )
        self.vocab_listbox.pack(side="left", fill="both", expand=True, padx=(4,0), pady=4)
        scrollbar.config(command=self.vocab_listbox.yview)
        self.vocab_listbox.bind("<<ListboxSelect>>", self._on_vocab_select)

        # Right: Detail View
        self.detail_fr = tk.Frame(split, bg=UI_CARD, highlightthickness=1, highlightbackground=UI_BORDER, padx=24, pady=24)
        split.add(self.detail_fr, stretch="always")
        
        # 内部布局
        self.v_word_var = tk.StringVar()
        self.v_meaning_var = tk.StringVar()
        self.v_stats_var = tk.StringVar()

        top_row = tk.Frame(self.detail_fr, bg=UI_CARD)
        top_row.pack(fill="x")
        word_lbl = tk.Label(top_row, textvariable=self.v_word_var, bg=UI_CARD, fg=UI_TEXT, font=tkfont.Font(family=FONT_FAMILY, size=24, weight="bold"))
        word_lbl.pack(side="left")
        
        btn_speak = tk.Button(top_row, text="♪", command=self._speak_current_vocab, bg=UI_CARD, fg=UI_INFO, relief="flat", bd=0, font=tkfont.Font(family=FONT_FAMILY, size=16), cursor="hand2")
        btn_speak.pack(side="left", padx=(8,0))
        
        self.btn_gen = tk.Button(top_row, text="✨ AI扩展", command=self._gen_example_current, bg=UI_CHIP, fg=UI_ACCENT, activebackground=UI_ACCENT, activeforeground="#ffffff", relief="flat", bd=0, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"), cursor="hand2", padx=10, pady=4)
        self.btn_gen.pack(side="right")
        hover_bind(self.btn_gen, UI_CHIP, UI_ACCENT, fg=UI_ACCENT, hover_fg="#ffffff")

        tk.Label(self.detail_fr, textvariable=self.v_stats_var, bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9)).pack(anchor="w", pady=(2, 16))
        
        tk.Label(self.detail_fr, text="翻译释义", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w")
        tk.Label(self.detail_fr, textvariable=self.v_meaning_var, bg=UI_CARD, fg=UI_MEANING, font=tkfont.Font(family=FONT_FAMILY, size=14), wraplength=400, justify="left").pack(anchor="w", pady=(4, 20))
        
        tk.Frame(self.detail_fr, bg=UI_BORDER_SOFT, height=1).pack(fill="x", pady=10)
        
        tk.Label(self.detail_fr, text="情景例句", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 6))
        
        ex_bg = UI_BG_ALT
        self.ex_wrap = tk.Frame(self.detail_fr, bg=ex_bg, highlightbackground=UI_BORDER_SOFT, highlightthickness=1, padx=16, pady=16)
        self.ex_wrap.pack(fill="x")
        
        self.v_ex_en = tk.StringVar()
        self.v_ex_zh = tk.StringVar()
        
        ex_top = tk.Frame(self.ex_wrap, bg=ex_bg)
        ex_top.pack(fill="x", pady=(0, 8))
        tk.Label(ex_top, textvariable=self.v_ex_en, bg=ex_bg, fg=UI_TEXT, font=tkfont.Font(family=FONT_FAMILY, size=12), wraplength=400, justify="left").pack(side="left", fill="x", expand=True)
        tk.Button(ex_top, text="♪", command=self._speak_current_example, bg=ex_bg, fg=UI_INFO, relief="flat", bd=0, font=tkfont.Font(family=FONT_FAMILY, size=12), cursor="hand2").pack(side="right", anchor="n")
        
        tk.Label(self.ex_wrap, textvariable=self.v_ex_zh, bg=ex_bg, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=10), wraplength=400, justify="left").pack(anchor="w")

        # 评分按钮
        tk.Frame(self.detail_fr, bg=UI_BORDER_SOFT, height=1).pack(fill="x", pady=20)
        tk.Label(self.detail_fr, text="掌握程度测评", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 10))
        
        grade_fr = tk.Frame(self.detail_fr, bg=UI_CARD)
        grade_fr.pack(fill="x")
        
        def _make_btn(parent, text, color, hover_color, cmd):
            b = tk.Button(parent, text=text, command=cmd, bg=UI_CARD, fg=color, activebackground=hover_color, activeforeground="#ffffff", relief="solid", bd=1, font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"), cursor="hand2", pady=8)
            hover_bind(b, UI_CARD, hover_color, fg=color, hover_fg="#ffffff")
            return b
            
        b1 = _make_btn(grade_fr, "✓ 认识", UI_OK, UI_OK_HOVER, lambda: self._apply_grade("know"))
        b1.pack(side="left", fill="x", expand=True, padx=(0, 8))
        b2 = _make_btn(grade_fr, "？ 模糊", UI_WARN, UI_WARN_HOVER, lambda: self._apply_grade("vague"))
        b2.pack(side="left", fill="x", expand=True, padx=(0, 8))
        b3 = _make_btn(grade_fr, "✕ 不认识", UI_DANGER, UI_DANGER_HOVER, lambda: self._apply_grade("unknown"))
        b3.pack(side="left", fill="x", expand=True)

    # ---- 生词本业务逻辑 ----
    def _load_vocab_list(self):
        self.vocab = vocab_store.load(VOCAB_PATH)
        normalize_scores(self.vocab)
        
        self.display_list = list(self.vocab)
        mode = self.sort_mode_var.get()
        if mode == "最新添加":
            self.display_list.reverse()
        elif mode == "低分优先":
            self.display_list.sort(key=lambda x: item_score(x))
        elif mode == "高分优先":
            self.display_list.sort(key=lambda x: -item_score(x))
        elif mode == "A-Z":
            self.display_list.sort(key=lambda x: str(x.get("word","")).lower())
            
        self.vocab_listbox.delete(0, tk.END)
        for it in self.display_list:
            self.vocab_listbox.insert(tk.END, " " + str(it.get("word", "")))
            
        if self.display_list:
            self.vocab_listbox.selection_set(0)
            self._on_vocab_select(None)
        else:
            self._clear_detail()

    def _clear_detail(self):
        self.v_word_var.set("暂无生词")
        self.v_meaning_var.set("")
        self.v_stats_var.set("")
        self.v_ex_en.set("")
        self.v_ex_zh.set("")

    def _current_vocab(self):
        sel = self.vocab_listbox.curselection()
        if not sel: return None
        return self.display_list[sel[0]]

    def _on_vocab_select(self, event):
        it = self._current_vocab()
        if not it: return
        self.v_word_var.set(str(it.get("word", "")))
        self.v_meaning_var.set(str(it.get("meaning", "")))
        
        sc = item_score(it)
        rev = int(it.get("reviews", 0))
        self.v_stats_var.set(f"熟练度: {sc:.1f} / 100    复习: {rev} 次")
        
        en = it.get("example", "")
        zh = it.get("example_zh", "")
        if not en and not zh:
            self.v_ex_en.set("暂无例句，点击上方 [✨ AI扩展] 生成")
            self.v_ex_zh.set("")
        else:
            self.v_ex_en.set(en)
            self.v_ex_zh.set(zh)
            
        # 缓存发音
        word = str(it.get("word", "")).strip()
        if word: tts.precache(word)

    def _speak_current_vocab(self):
        it = self._current_vocab()
        if it and it.get("word"):
            tts.speak_async(it.get("word"))

    def _speak_current_example(self):
        it = self._current_vocab()
        if it and it.get("example"):
            tts.speak_async(it.get("example"))

    def _gen_example_current(self):
        it = self._current_vocab()
        if not it: return
        if deepseek.get_client() is None:
            messagebox.showwarning("提示", "请先在 api_key.txt 中填写 DeepSeek API Key。")
            return
            
        self.btn_gen.configure(state="disabled", text="生成中...")
        word = str(it.get("word", ""))
        meaning = str(it.get("meaning", ""))
        
        def _worker():
            en, zh = deepseek.generate_example(word, meaning)
            if en and zh:
                # 必须更新原始 self.vocab 中的引用
                orig_it = vocab_store.find_item(self.vocab, word)
                if orig_it:
                    orig_it["example"] = en
                    orig_it["example_zh"] = zh
                    vocab_store.save(self.vocab, VOCAB_PATH)
            
            if self.root.winfo_exists():
                self.root.after(0, self._on_gen_done)
                
        threading.Thread(target=_worker, daemon=True).start()

    def _on_gen_done(self):
        self.btn_gen.configure(state="normal", text="✨ AI扩展")
        self._on_vocab_select(None) # 重新渲染当前

    def _apply_grade(self, grade):
        it = self._current_vocab()
        if not it: return
        delta = GRADE_DELTA.get((grade, True)) # 总是显示了意思
        if delta is None: return
        
        orig_it = vocab_store.find_item(self.vocab, str(it.get("word","")))
        if orig_it:
            old = item_score(orig_it)
            new = max(SCORE_MIN, min(SCORE_MAX, old + delta))
            orig_it["score"] = round(new, 1)
            orig_it["reviews"] = int(orig_it.get("reviews") or 0) + 1
            vocab_store.save(self.vocab, VOCAB_PATH)
            
        # 自动跳下一个
        sel = self.vocab_listbox.curselection()
        if sel:
            idx = sel[0]
            if idx + 1 < self.vocab_listbox.size():
                self.vocab_listbox.selection_clear(0, tk.END)
                self.vocab_listbox.selection_set(idx + 1)
                self.vocab_listbox.see(idx + 1)
                self._on_vocab_select(None)
            else:
                self._load_vocab_list() # 重新排序或刷新

    # ---- 生命周期 ----
    def _on_close(self):
        self.hotkey_listener.stop()
        self.root.destroy()

    def run(self):
        self.floating = FloatingWindow(self.root, VOCAB_PATH)

        def _on_hotkey_fail():
            self.root.after(0, lambda: self.status_var.set("错误：Ctrl + L 注册失败，可能被占用"))

        self.hotkey_listener.start(on_register_fail=_on_hotkey_fail)
        self.status_var.set("已开启 — 划词后按 Ctrl + L 即可翻译")
        self.root.mainloop()

if __name__ == "__main__":
    UnifiedApp().run()
