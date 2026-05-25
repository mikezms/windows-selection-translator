import os
import sys
import threading
import time
import random
import tkinter as tk
from tkinter import font as tkfont, scrolledtext, messagebox, ttk

import hotkey as hk
import app_config
import translator
import deepseek
import tts
import updater
import vocab_store
from app_paths import VOCAB_PATH
from floating_window import FloatingWindow
from settings_dialog import ApiSettingsDialog
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
from version import APP_VERSION

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class UnifiedApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"得意划词翻译 {APP_VERSION}")
        self.root.geometry("860x640")
        self.root.minsize(700, 500)
        self.root.configure(bg=UI_BG)

        # 全局状态
        self.status_var = tk.StringVar(value="就绪")
        self.enable_var = tk.BooleanVar(value=True)
        self.floating_var = tk.BooleanVar(value=True)
        self.app_config = app_config.load_config()
        self.translate_source_var = tk.StringVar(value=self.app_config.get("translate_source", "mymemory"))
        self.hotkey_var = tk.StringVar(value=str(self.app_config.get("hotkey") or app_config.DEFAULT_HOTKEY))
        
        self._enabled_lock = threading.Lock()
        self._translate_enabled = True

        # 生词本状态
        self.vocab = vocab_store.load(VOCAB_PATH)
        normalize_scores(self.vocab)
        self.sort_mode_var = tk.StringVar(value="最新添加")
        self.vocab_filter_var = tk.StringVar(value="全部")
        self._selected_vocab_index = 0
        self.vocab_rows = []
        self.vocab_filter_buttons = {}
        
        # 悬浮窗和快捷键
        self.floating = None
        self.hotkey_listener = hk.HotkeyListener(on_hotkey=self._do_translate_job, hotkey=self.hotkey_var.get())
        self._update_progress_win = None
        self._update_progress_label_var = tk.StringVar(value="")
        self._update_progress_percent_var = tk.DoubleVar(value=0.0)
        self._update_progress_bar = None
        self._update_cancel_event = threading.Event()

        self._build_ui()
        self._refresh_saved_model_switch_menu()
        self._load_vocab_list()

    # ---- 翻译业务逻辑 ----
    def _is_translate_enabled(self):
        with self._enabled_lock:
            return self._translate_enabled

    def _on_enable_toggle(self):
        with self._enabled_lock:
            self._translate_enabled = bool(self.enable_var.get())
        if self._translate_enabled:
            self.status_var.set(f"已开启 — 划词后按 {self.hotkey_var.get()} 即可翻译")
        else:
            self.status_var.set("已暂停 — 不会响应快捷键")

    def _append_log(self, original, result):
        ts = time.strftime("%H:%M:%S")
        item = {"timestamp": ts, "original": original, "translated": result}
        self._insert_history_item(item, at_top=True)
        
        # 存入文件
        import history_store
        hist_items = history_store.load()
        history_store.add(hist_items, ts, original, result)
        history_store.save(hist_items)

    def _clear_log(self):
        self._clear_history_view()
        
        import history_store
        history_store.save([])

    def _do_translate_job(self):
        if not self._is_translate_enabled(): return
        text = hk.copy_selected_text()
        if not text:
            self.root.after(0, lambda: self._show_error("提示", f"未检测到选中文本，请先划词再按 {self.hotkey_var.get()}"))
            return
        text = text.strip()
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
        tk.Label(brand, text="⚡ 得意翻译", bg=UI_BG_ALT, fg=UI_ACCENT, font=tkfont.Font(family=FONT_FAMILY, size=16, weight="bold")).pack(anchor="w")

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

        tk.Label(settings, text="快捷开关", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 10))
        
        chk_kw = dict(bg=UI_CARD, fg=UI_TEXT_SOFT, activebackground=UI_CARD, activeforeground=UI_TEXT,
                      selectcolor=UI_CHIP, font=tkfont.Font(family=FONT_FAMILY, size=9), highlightthickness=0, bd=0)
        
        tk.Checkbutton(settings, text="启用快捷键翻译", variable=self.enable_var, command=self._on_enable_toggle, **chk_kw).pack(anchor="w", pady=2)
        tk.Checkbutton(settings, text="翻译后弹出悬浮窗", variable=self.floating_var, **chk_kw).pack(anchor="w", pady=2)

        tk.Frame(settings, bg=UI_BORDER_SOFT, height=1).pack(fill="x", pady=10)
        tk.Label(settings, text="翻译方式", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 6))
        
        rb_kw = dict(bg=UI_CARD, activebackground=UI_CARD, fg=UI_TEXT_SOFT, selectcolor=UI_CHIP,
                     font=tkfont.Font(family=FONT_FAMILY, size=9), highlightthickness=0, bd=0)
        tk.Radiobutton(settings, text="通用快速翻译", variable=self.translate_source_var, value="mymemory", command=self._on_translate_source_change, **rb_kw).pack(anchor="w")
        tk.Radiobutton(settings, text="Google 翻译", variable=self.translate_source_var, value="google", command=self._on_translate_source_change, **rb_kw).pack(anchor="w")
        tk.Radiobutton(settings, text="AI 技术语境翻译", variable=self.translate_source_var, value="deepseek", command=self._on_translate_source_change, **rb_kw).pack(anchor="w")

        tk.Button(
            settings, text="API 设置", command=self._open_api_settings,
            bg=UI_CHIP, fg=UI_ACCENT, activebackground=UI_ACCENT,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            cursor="hand2", pady=6,
        ).pack(fill="x", pady=(10, 0))

        model_row = tk.Frame(settings, bg=UI_CARD)
        model_row.pack(fill="x", pady=(10, 0))
        tk.Label(model_row, text="历史模型", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w")
        self.saved_model_switch_var = tk.StringVar(value="")
        self.saved_model_switch_menu = tk.OptionMenu(model_row, self.saved_model_switch_var, "")
        self.saved_model_switch_menu.configure(
            bg=UI_CHIP, fg=UI_ACCENT, activebackground=UI_ACCENT,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            width=18,
        )
        self.saved_model_switch_menu.pack(fill="x", pady=(4, 0))
        tk.Button(
            model_row, text="切换模型", command=self._switch_saved_model,
            bg=UI_CARD, fg=UI_ACCENT, activebackground=UI_CHIP,
            activeforeground=UI_ACCENT, relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            cursor="hand2", pady=4,
        ).pack(fill="x", pady=(6, 0))

        hotkey_row = tk.Frame(settings, bg=UI_CARD)
        hotkey_row.pack(fill="x", pady=(10, 0))
        tk.Label(hotkey_row, text="快捷键", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w")
        tk.Entry(
            hotkey_row, textvariable=self.hotkey_var, width=16,
            bg="#ffffff", fg=UI_TEXT, insertbackground=UI_TEXT,
            relief="solid", bd=1, highlightthickness=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(fill="x", pady=(4, 0))
        tk.Button(
            hotkey_row, text="应用快捷键", command=self._apply_hotkey_setting,
            bg=UI_CARD, fg=UI_ACCENT, activebackground=UI_CHIP,
            activeforeground=UI_ACCENT, relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            cursor="hand2", pady=4,
        ).pack(fill="x", pady=(6, 0))

    def _on_translate_source_change(self):
        self.app_config = app_config.load_config()
        self.app_config["translate_source"] = self.translate_source_var.get()
        app_config.save_config(self.app_config)

    def _open_api_settings(self):
        dialog = ApiSettingsDialog(self.root, first_run=False)
        if dialog.result:
            self.app_config = app_config.load_config()
            deepseek.reset_client_cache()
            self._refresh_saved_model_switch_menu()
            self.hotkey_var.set(str(self.app_config.get("hotkey") or app_config.DEFAULT_HOTKEY))
            self._apply_hotkey_setting()
            self.status_var.set(f"已保存 API 设置：{app_config.provider_label(self.app_config.get('ai_provider', 'deepseek'))}")

    def _saved_model_label(self, item):
        provider = str(item.get("provider") or "custom")
        base_url = str(item.get("base_url") or "").strip()
        model = str(item.get("model") or "").strip()
        if not model:
            return ""
        label = model if not base_url else f"{model} @ {base_url}"
        return f"{provider}: {label}" if provider != "custom" else label

    def _refresh_saved_model_switch_menu(self):
        self.app_config = app_config.load_config()
        models = list(self.app_config.get("ai_models") or [])
        labels = [self._saved_model_label(item) for item in models if self._saved_model_label(item)]
        menu = self.saved_model_switch_menu["menu"]
        menu.delete(0, "end")
        if not labels:
            labels = ["暂无历史模型"]
        for label in labels:
            menu.add_command(label=label, command=lambda v=label: self.saved_model_switch_var.set(v))
        self.saved_model_switch_var.set(labels[0])

    def _switch_saved_model(self):
        selected = self.saved_model_switch_var.get()
        self.app_config = app_config.load_config()
        for item in list(self.app_config.get("ai_models") or []):
            if self._saved_model_label(item) == selected:
                self.app_config["ai_provider"] = str(item.get("provider") or "custom")
                self.app_config["ai_base_url"] = str(item.get("base_url") or "")
                self.app_config["ai_model"] = str(item.get("model") or "")
                app_config.save_config(self.app_config)
                self.translate_source_var.set(self.app_config.get("translate_source", self.translate_source_var.get()))
                self.hotkey_var.set(str(self.app_config.get("hotkey") or app_config.DEFAULT_HOTKEY))
                self._apply_hotkey_setting()
                self.status_var.set(f"已切换模型：{self.app_config['ai_model']}")
                return
        self.status_var.set("没有可切换的历史模型")

    def _ensure_api_settings(self):
        if not app_config.needs_first_run_setup():
            return
        dialog = ApiSettingsDialog(self.root, first_run=True)
        if dialog.result and app_config.is_ai_configured():
            self.app_config = app_config.load_config()
            deepseek.reset_client_cache()
            self._refresh_saved_model_switch_menu()
            self.hotkey_var.set(str(self.app_config.get("hotkey") or app_config.DEFAULT_HOTKEY))
            self._apply_hotkey_setting()
            self.status_var.set("API 设置已保存，可以开始使用")
            return
        messagebox.showwarning("需要 API Key", "请先完成 API 设置后再使用得意翻译。")
        self.root.after(0, self._on_close)

    def _check_for_updates_async(self):
        def _worker():
            try:
                update = updater.check_update()
            except Exception:
                return
            if update and self.root.winfo_exists():
                self.root.after(0, lambda u=update: self._show_update_prompt(u))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_prompt(self, update):
        version = update.version
        notes = update.notes.strip()
        msg = f"发现新版本：{version}\n当前版本：{APP_VERSION}"
        if notes:
            msg += f"\n\n更新内容：\n{notes}"
        msg += "\n\n是否立即在应用内下载并更新？"
        if messagebox.askyesno("发现新版本", msg):
            self._start_update_download(update)

    def _apply_hotkey_setting(self):
        hotkey = app_config.normalize_hotkey(self.hotkey_var.get())
        self.hotkey_var.set(hotkey)
        self.app_config = app_config.load_config()
        self.app_config["hotkey"] = hotkey
        app_config.save_config(self.app_config)
        if hasattr(self, "hotkey_listener") and self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = hk.HotkeyListener(on_hotkey=self._do_translate_job, hotkey=hotkey)
            self.hotkey_listener.start(on_register_fail=lambda: self.root.after(0, lambda: self.status_var.set(f"错误：快捷键 {hotkey} 注册失败，可能被占用")))
            self.status_var.set(f"快捷键已更新为 {hotkey}")

    def _start_update_download(self, update):
        if self._update_progress_win and self._update_progress_win.winfo_exists():
            self._update_progress_win.lift()
            return

        self._update_cancel_event.clear()
        self._update_progress_percent_var.set(0.0)
        self._update_progress_label_var.set("准备下载更新...")

        win = tk.Toplevel(self.root)
        win.title("下载更新")
        win.geometry("420x170")
        win.resizable(False, False)
        win.configure(bg=UI_BG)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self._cancel_update_download)
        self._update_progress_win = win

        body = tk.Frame(win, bg=UI_BG, padx=20, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text=f"正在下载 SnapTranslate {update.version}",
            bg=UI_BG, fg=UI_TEXT,
            font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
        ).pack(anchor="w")
        tk.Label(
            body, textvariable=self._update_progress_label_var,
            bg=UI_BG, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(anchor="w", pady=(8, 10))

        self._update_progress_bar = ttk.Progressbar(
            body, variable=self._update_progress_percent_var, maximum=100, mode="determinate"
        )
        self._update_progress_bar.pack(fill="x")

        tk.Button(
            body, text="取消下载", command=self._cancel_update_download,
            bg=UI_BG_ALT, fg=UI_TEXT_SOFT, activebackground=UI_CHIP, activeforeground=UI_ACCENT,
            relief="flat", bd=0, cursor="hand2", padx=14, pady=6,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
        ).pack(anchor="e", pady=(16, 0))

        def _progress(downloaded, total):
            if self.root.winfo_exists():
                self.root.after(0, lambda d=downloaded, t=total: self._on_update_download_progress(d, t))

        def _worker():
            try:
                local_path = updater.download_update(update, _progress, self._update_cancel_event)
            except Exception as exc:
                if self.root.winfo_exists():
                    self.root.after(0, lambda e=exc: self._finish_update_download_error(e))
                return
            if self.root.winfo_exists():
                self.root.after(0, lambda p=local_path: self._finish_update_download_success(p))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_download_progress(self, downloaded, total):
        if total:
            percent = min(100.0, downloaded * 100.0 / total)
            self._update_progress_percent_var.set(percent)
            self._update_progress_label_var.set(
                f"已下载 {self._format_bytes(downloaded)} / {self._format_bytes(total)}"
            )
        else:
            self._update_progress_label_var.set(f"已下载 {self._format_bytes(downloaded)}")

    def _finish_update_download_error(self, exc):
        self._destroy_update_progress_win()
        if self._update_cancel_event.is_set():
            self.status_var.set("已取消更新下载")
            return
        messagebox.showerror("更新失败", f"更新包下载失败：\n{exc}")

    def _finish_update_download_success(self, local_path):
        self._destroy_update_progress_win()
        self.status_var.set("更新包已下载完成")
        if messagebox.askyesno("下载完成", "更新包已下载完成。\n\n是否关闭当前应用并开始安装？"):
            try:
                updater.launch_installer(local_path)
            except Exception as exc:
                messagebox.showerror("启动安装失败", f"无法启动安装包：\n{exc}")
                return
            self._on_close()

    def _cancel_update_download(self):
        self._update_cancel_event.set()
        self._update_progress_label_var.set("正在取消下载...")

    def _destroy_update_progress_win(self):
        if self._update_progress_win and self._update_progress_win.winfo_exists():
            self._update_progress_win.destroy()
        self._update_progress_win = None
        self._update_progress_bar = None

    @staticmethod
    def _format_bytes(size):
        size = float(size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024

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
        
        self.history_text = scrolledtext.ScrolledText(
            card, wrap="word", state="disabled", font=tkfont.Font(family=FONT_FAMILY, size=10),
            bg=UI_LOG_BG, fg=UI_TEXT, insertbackground=UI_TEXT, relief="flat", bd=0,
            padx=16, pady=16, highlightthickness=0, spacing1=3, spacing3=7
        )
        self.history_text.pack(fill="both", expand=True)
        self.history_text.tag_configure(
            "card_start",
            spacing1=10,
            lmargin1=10,
            lmargin2=10,
            rmargin=10,
        )
        self.history_text.tag_configure(
            "time",
            foreground=UI_ACCENT,
            background=UI_CHIP,
            font=tkfont.Font(family=FONT_FAMILY, size=8, weight="bold"),
        )
        self.history_text.tag_configure(
            "orig",
            foreground=UI_TEXT,
            font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
            lmargin1=10,
            lmargin2=10,
            rmargin=10,
        )
        self.history_text.tag_configure(
            "section",
            foreground=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=8, weight="bold"),
            lmargin1=10,
            lmargin2=10,
            rmargin=10,
        )
        self.history_text.tag_configure(
            "trans",
            foreground=UI_ACCENT,
            font=tkfont.Font(family=FONT_FAMILY, size=10),
            lmargin1=10,
            lmargin2=10,
            rmargin=10,
        )
        self.history_text.tag_configure(
            "note",
            foreground=UI_TEXT_SOFT,
            background=UI_BG_ALT,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
            lmargin1=18,
            lmargin2=18,
            rmargin=18,
            spacing1=6,
            spacing3=6,
        )
        self.history_text.tag_configure(
            "divider",
            foreground=UI_BORDER,
            lmargin1=10,
            lmargin2=10,
            rmargin=10,
        )

        # 状态提示
        status = tk.Frame(self.history_frame, bg=UI_STATUS_BG, padx=12, pady=10, highlightthickness=0)
        status.pack(fill="x", pady=(16, 0))
        tk.Label(status, text="●", bg=UI_STATUS_BG, fg=UI_ACCENT, font=tkfont.Font(family=FONT_FAMILY, size=8)).pack(side="left", padx=(0, 6))
        tk.Label(status, textvariable=self.status_var, bg=UI_STATUS_BG, fg=UI_TEXT_SOFT, font=tkfont.Font(family=FONT_FAMILY, size=9)).pack(side="left")

        # 加载历史记录
        import history_store
        hist_items = history_store.load()
        self._render_history(hist_items)

    def _render_history(self, items):
        self._clear_history_view()
        self.history_text.configure(state="normal")
        for item in reversed(items or []):
            self._write_history_item(item)
        self.history_text.configure(state="disabled")
        self.history_text.yview_moveto(0)

    def _clear_history_view(self):
        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", "end")
        self.history_text.configure(state="disabled")

    @staticmethod
    def _split_translation_sections(text):
        raw = str(text or "").strip()
        markers = ["💡 技术背景说明：", "💡 通俗解释（说人话）：", "技术背景说明：", "通俗解释（说人话）："]
        for marker in markers:
            if marker in raw:
                before, after = raw.split(marker, 1)
                return before.strip(), (marker + after).strip()
        return raw, ""

    def _insert_history_item(self, item, at_top=False):
        self.history_text.configure(state="normal")
        self._write_history_item(item, index="1.0" if at_top else "end")
        self.history_text.configure(state="disabled")
        if at_top:
            self.history_text.yview_moveto(0)

    def _write_history_item(self, item, index="end"):
        ts = str(item.get("timestamp", ""))
        original = str(item.get("original", ""))
        translated = str(item.get("translated", ""))
        main_trans, note = self._split_translation_sections(translated)

        segments = [
            (f"{ts}  ", ("time", "card_start")),
            (f"{original}\n", ("orig", "card_start")),
            ("译文\n", ("section",)),
            (f"{main_trans or translated}\n", ("trans",)),
        ]
        if note:
            segments.append((f"{note}\n", ("note",)))
        segments.append(("\n", ("divider",)))

        if index == "1.0":
            for text, tags in reversed(segments):
                self.history_text.insert(index, text, tags)
            return
        for text, tags in segments:
            self.history_text.insert(index, text, tags)

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

        filter_fr = tk.Frame(left_top, bg=UI_CARD)
        filter_fr.pack(fill="x", pady=(8, 0))
        self.vocab_filter_buttons = {}
        for kind in ("全部", "单词", "短语", "句子"):
            btn = tk.Button(
                filter_fr, text=kind,
                command=lambda k=kind: self._set_vocab_filter(k),
                relief="flat", bd=0, padx=0, pady=5,
                font=tkfont.Font(family=FONT_FAMILY, size=8, weight="bold"),
                cursor="hand2",
            )
            btn.pack(side="left", fill="x", expand=True, padx=(0, 4 if kind != "句子" else 0))
            btn.bind("<Enter>", lambda _e, b=btn, k=kind: self._on_vocab_filter_hover(b, k, True))
            btn.bind("<Leave>", lambda _e, b=btn, k=kind: self._on_vocab_filter_hover(b, k, False))
            self.vocab_filter_buttons[kind] = btn
        self._refresh_vocab_filter_buttons()

        list_frame = tk.Frame(left_fr, bg=UI_CARD)
        list_frame.pack(fill="both", expand=True)
        self.vocab_canvas = tk.Canvas(
            list_frame, bg=UI_CARD, highlightthickness=0, bd=0,
            yscrollincrement=18
        )
        scrollbar = tk.Scrollbar(list_frame, command=self.vocab_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.vocab_canvas.pack(side="left", fill="both", expand=True)
        self.vocab_canvas.configure(yscrollcommand=scrollbar.set)
        self.vocab_list_inner = tk.Frame(self.vocab_canvas, bg=UI_CARD)
        self._vocab_window = self.vocab_canvas.create_window(
            (0, 0), window=self.vocab_list_inner, anchor="nw"
        )
        self.vocab_list_inner.bind("<Configure>", self._on_vocab_list_configure)
        self.vocab_canvas.bind("<Configure>", self._on_vocab_canvas_configure)
        self.vocab_canvas.bind("<MouseWheel>", self._on_vocab_mousewheel)

        # Right: Detail View
        self.detail_fr = tk.Frame(split, bg=UI_CARD, highlightthickness=1, highlightbackground=UI_BORDER, padx=24, pady=24)
        split.add(self.detail_fr, stretch="always")
        
        # 内部布局
        self.v_word_var = tk.StringVar()
        self.v_meaning_var = tk.StringVar()
        self.v_stats_var = tk.StringVar()

        # 将详情区分割为顶部(可弹性)和底部(固定停靠)
        self.detail_bottom_fr = tk.Frame(self.detail_fr, bg=UI_CARD)
        self.detail_bottom_fr.pack(side="bottom", fill="x")
        
        self.detail_top_fr = tk.Frame(self.detail_fr, bg=UI_CARD)
        self.detail_top_fr.pack(side="top", fill="both", expand=True)
        
        # 内部布局 - 顶部容器
        self.v_word_var = tk.StringVar()
        self.v_meaning_var = tk.StringVar()
        self.v_stats_var = tk.StringVar()

        top_row = tk.Frame(self.detail_top_fr, bg=UI_CARD)
        top_row.pack(fill="x")
        title_col = tk.Frame(top_row, bg=UI_CARD)
        title_col.pack(side="left", fill="x", expand=True)
        self.word_lbl = tk.Label(
            title_col, textvariable=self.v_word_var, bg=UI_CARD, fg=UI_TEXT,
            font=tkfont.Font(family=FONT_FAMILY, size=24, weight="bold"),
            anchor="w", justify="left"
        )
        self.word_lbl.pack(fill="x", anchor="w")

        action_row = tk.Frame(top_row, bg=UI_CARD)
        action_row.pack(side="right", anchor="n", padx=(12, 0))
        btn_speak = tk.Button(action_row, text="♪", command=self._speak_current_vocab, bg=UI_CARD, fg=UI_INFO, relief="flat", bd=0, font=tkfont.Font(family=FONT_FAMILY, size=16), cursor="hand2")
        btn_speak.pack(side="left", padx=(0, 8))
        
        self.btn_gen = tk.Button(action_row, text="✨ AI扩展", command=self._gen_example_current, bg=UI_CHIP, fg=UI_ACCENT, activebackground=UI_ACCENT, activeforeground="#ffffff", relief="flat", bd=0, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"), cursor="hand2", padx=10, pady=4)
        self.btn_gen.pack(side="left")
        hover_bind(self.btn_gen, UI_CHIP, UI_ACCENT, fg=UI_ACCENT, hover_fg="#ffffff")

        tk.Label(self.detail_top_fr, textvariable=self.v_stats_var, bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9)).pack(anchor="w", pady=(2, 14))

        self.source_wrap = tk.Frame(self.detail_top_fr, bg=UI_BG_ALT, highlightbackground=UI_BORDER_SOFT, highlightthickness=1, padx=12, pady=10)
        tk.Label(self.source_wrap, text="完整原文", bg=UI_BG_ALT, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 6))
        self.source_text = tk.Text(
            self.source_wrap, height=3, wrap="word", state="disabled",
            bg=UI_BG_ALT, fg=UI_TEXT_SOFT, relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=10),
            padx=0, pady=0, highlightthickness=0, cursor="arrow"
        )
        self.source_text.pack(fill="x")
        
        self.meaning_title_lbl = tk.Label(self.detail_top_fr, text="翻译释义", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"))
        self.meaning_title_lbl.pack(anchor="w")
        self.meaning_lbl = tk.Label(self.detail_top_fr, textvariable=self.v_meaning_var, bg=UI_CARD, fg=UI_MEANING, font=tkfont.Font(family=FONT_FAMILY, size=14), anchor="w", justify="left")
        self.meaning_lbl.pack(fill="x", anchor="w", pady=(4, 20))
        
        tk.Frame(self.detail_top_fr, bg=UI_BORDER_SOFT, height=1).pack(fill="x", pady=10)
        
        tk.Label(self.detail_top_fr, text="情景例句", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 6))
        
        ex_bg = UI_BG_ALT
        self.ex_wrap = tk.Frame(self.detail_top_fr, bg=ex_bg, highlightbackground=UI_BORDER_SOFT, highlightthickness=1, padx=16, pady=16)
        self.ex_wrap.pack(fill="x")
        
        self.v_ex_en = tk.StringVar()
        self.v_ex_zh = tk.StringVar()
        
        ex_top = tk.Frame(self.ex_wrap, bg=ex_bg)
        ex_top.pack(fill="x", pady=(0, 8))
        self.ex_en_lbl = tk.Label(ex_top, textvariable=self.v_ex_en, bg=ex_bg, fg=UI_TEXT, font=tkfont.Font(family=FONT_FAMILY, size=12), anchor="w", justify="left")
        self.ex_en_lbl.pack(side="left", fill="x", expand=True)
        tk.Button(ex_top, text="♪", command=self._speak_current_example, bg=ex_bg, fg=UI_INFO, relief="flat", bd=0, font=tkfont.Font(family=FONT_FAMILY, size=12), cursor="hand2").pack(side="right", anchor="n")
        
        self.ex_zh_lbl = tk.Label(self.ex_wrap, textvariable=self.v_ex_zh, bg=ex_bg, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=10), anchor="w", justify="left")
        self.ex_zh_lbl.pack(fill="x", anchor="w")

        # 内部布局 - 底部评分容器
        tk.Frame(self.detail_bottom_fr, bg=UI_BORDER_SOFT, height=1).pack(fill="x", pady=(10, 10))
        tk.Label(self.detail_bottom_fr, text="掌握程度测评", bg=UI_CARD, fg=UI_TEXT_MUTED, font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")).pack(anchor="w", pady=(0, 10))
        
        grade_fr = tk.Frame(self.detail_bottom_fr, bg=UI_CARD)
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

        # 动态调整换行长度
        self.detail_fr.bind("<Configure>", self._on_detail_resize)

    def _on_vocab_list_configure(self, event):
        self.vocab_canvas.configure(scrollregion=self.vocab_canvas.bbox("all"))

    def _on_vocab_canvas_configure(self, event):
        self.vocab_canvas.itemconfigure(self._vocab_window, width=event.width)
        for row in getattr(self, "vocab_rows", []):
            lbl = row.get("label")
            if lbl:
                lbl.configure(wraplength=max(120, event.width - 28))

    def _on_vocab_mousewheel(self, event):
        self.vocab_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _set_vocab_filter(self, kind):
        if kind == self.vocab_filter_var.get():
            return
        self.vocab_filter_var.set(kind)
        self._selected_vocab_index = 0
        self._refresh_vocab_filter_buttons()
        self._load_vocab_list()

    def _on_vocab_filter_hover(self, btn, kind, entering):
        selected = kind == self.vocab_filter_var.get()
        if selected:
            return
        btn.configure(bg=UI_CHIP if entering else UI_BG_ALT, fg=UI_ACCENT if entering else UI_TEXT_MUTED)

    def _refresh_vocab_filter_buttons(self):
        current = self.vocab_filter_var.get()
        for kind, btn in getattr(self, "vocab_filter_buttons", {}).items():
            selected = kind == current
            btn.configure(
                bg=UI_ACCENT if selected else UI_BG_ALT,
                fg="#ffffff" if selected else UI_TEXT_MUTED,
                activebackground=UI_ACCENT_HOVER if selected else UI_CHIP,
                activeforeground="#ffffff" if selected else UI_ACCENT,
            )

    @staticmethod
    def _entry_kind(text):
        s = (text or "").strip()
        if len(s) > 55 or any(p in s for p in ".!?。！？；;：:"):
            return "句子"
        if " " in s:
            return "短语"
        return "单词"

    @staticmethod
    def _list_preview(text, max_chars=90):
        s = " ".join(str(text or "").split())
        if len(s) <= max_chars:
            return s
        return s[:max_chars - 3].rstrip() + "..."

    def _make_vocab_row(self, parent, item, idx):
        word = str(item.get("word", ""))
        score = item_score(item)
        kind = self._entry_kind(word)

        row = tk.Frame(parent, bg=UI_CARD, padx=10, pady=8, cursor="hand2")
        row.pack(fill="x", padx=6, pady=(0, 2))

        label = tk.Label(
            row, text=self._list_preview(word), bg=UI_CARD, fg=UI_TEXT,
            font=tkfont.Font(family=FONT_FAMILY, size=10),
            anchor="w", justify="left", cursor="hand2"
        )
        label.pack(fill="x", anchor="w")

        meta = tk.Label(
            row, text=f"{kind}  ·  {score:.0f}/100", bg=UI_CARD, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=8),
            anchor="w", cursor="hand2"
        )
        meta.pack(fill="x", anchor="w", pady=(2, 0))

        row_info = {"frame": row, "label": label, "meta": meta}
        self.vocab_rows.append(row_info)
        for widget in (row, label, meta):
            widget.bind("<Button-1>", lambda _e, i=idx: self._select_vocab_index(i))
            widget.bind("<MouseWheel>", self._on_vocab_mousewheel)
        return row_info

    def _select_vocab_index(self, idx):
        if idx < 0 or idx >= len(self.display_list):
            return
        self._selected_vocab_index = idx
        self._refresh_vocab_row_styles()
        self._on_vocab_select(None)

    def _refresh_vocab_row_styles(self):
        for idx, row in enumerate(getattr(self, "vocab_rows", [])):
            selected = idx == self._selected_vocab_index
            bg = UI_CHIP if selected else UI_CARD
            fg = UI_ACCENT if selected else UI_TEXT
            meta_fg = UI_ACCENT_DARK if selected else UI_TEXT_MUTED
            for widget in (row["frame"], row["label"], row["meta"]):
                widget.configure(bg=bg)
            row["label"].configure(fg=fg)
            row["meta"].configure(fg=meta_fg)

    def _scroll_selected_vocab_into_view(self):
        if not getattr(self, "vocab_rows", None):
            return
        idx = min(max(self._selected_vocab_index, 0), len(self.vocab_rows) - 1)
        row = self.vocab_rows[idx]["frame"]
        self.root.update_idletasks()
        inner_h = max(1, self.vocab_list_inner.winfo_height())
        canvas_h = max(1, self.vocab_canvas.winfo_height())
        y = row.winfo_y()
        row_h = row.winfo_height()
        top = self.vocab_canvas.canvasy(0)
        bottom = top + canvas_h
        if y < top:
            self.vocab_canvas.yview_moveto(y / inner_h)
        elif y + row_h > bottom:
            self.vocab_canvas.yview_moveto(max(0, (y + row_h - canvas_h) / inner_h))

    def _font_for_vocab_title(self, text):
        n = len(str(text or ""))
        if n <= 24:
            return tkfont.Font(family=FONT_FAMILY, size=24, weight="bold")
        if n <= 70:
            return tkfont.Font(family=FONT_FAMILY, size=18, weight="bold")
        return tkfont.Font(family=FONT_FAMILY, size=13, weight="bold")

    def _update_source_block(self, text):
        show = self._entry_kind(text) != "单词"
        if show:
            if not self.source_wrap.winfo_ismapped():
                self.source_wrap.pack(fill="x", pady=(0, 16), before=self.meaning_title_lbl)
            self.source_text.configure(state="normal")
            self.source_text.delete("1.0", "end")
            self.source_text.insert("1.0", str(text or ""))
            line_count = max(3, min(6, int(len(str(text or "")) / 54) + 2))
            self.source_text.configure(height=line_count, state="disabled")
        else:
            self.source_wrap.pack_forget()

    def _on_detail_resize(self, event):
        w = event.width
        # safe wrap limits based on the width of detail_fr
        title_wrap = max(160, w - 180)
        source_wrap = max(100, w - 80)
        meaning_wrap = max(100, w - 48)
        ex_en_wrap = max(100, w - 80) # padding for the button
        ex_zh_wrap = max(100, w - 48)
        
        if hasattr(self, 'word_lbl'):
            self.word_lbl.configure(wraplength=title_wrap)
        if hasattr(self, 'source_text'):
            self.source_text.configure(width=max(20, source_wrap // 8))
        if hasattr(self, 'meaning_lbl'):
            self.meaning_lbl.configure(wraplength=meaning_wrap)
        if hasattr(self, 'ex_en_lbl'):
            self.ex_en_lbl.configure(wraplength=ex_en_wrap)
        if hasattr(self, 'ex_zh_lbl'):
            self.ex_zh_lbl.configure(wraplength=ex_zh_wrap)

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

        selected_filter = self.vocab_filter_var.get()
        if selected_filter != "全部":
            self.display_list = [
                it for it in self.display_list
                if self._entry_kind(str(it.get("word", ""))) == selected_filter
            ]
            
        for child in self.vocab_list_inner.winfo_children():
            child.destroy()
        self.vocab_rows = []
        for idx, it in enumerate(self.display_list):
            self._make_vocab_row(self.vocab_list_inner, it, idx)

        if self.display_list:
            self._selected_vocab_index = min(self._selected_vocab_index, len(self.display_list) - 1)
            self._refresh_vocab_row_styles()
            self._scroll_selected_vocab_into_view()
            self._on_vocab_select(None)
        else:
            self._selected_vocab_index = 0
            self._clear_detail()

    def _clear_detail(self):
        self.v_word_var.set("暂无生词")
        self.v_meaning_var.set("")
        self.v_stats_var.set("")
        self.v_ex_en.set("")
        self.v_ex_zh.set("")
        if hasattr(self, "source_wrap"):
            self.source_wrap.pack_forget()

    def _current_vocab(self):
        if not self.display_list:
            return None
        if self._selected_vocab_index < 0 or self._selected_vocab_index >= len(self.display_list):
            return None
        return self.display_list[self._selected_vocab_index]

    def _on_vocab_select(self, event):
        it = self._current_vocab()
        if not it: return
        word = str(it.get("word", ""))
        self.v_word_var.set(word)
        if hasattr(self, "word_lbl"):
            self.word_lbl.configure(font=self._font_for_vocab_title(word))
        if hasattr(self, "source_wrap"):
            self._update_source_block(word)
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
        if not app_config.is_ai_configured():
            messagebox.showwarning("提示", "请先在 API 设置中填写服务商、模型和 API Key。")
            self._open_api_settings()
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
        idx = self._selected_vocab_index
        if idx + 1 < len(self.display_list):
            self._select_vocab_index(idx + 1)
            self._scroll_selected_vocab_into_view()
        else:
            self._selected_vocab_index = 0
            self._load_vocab_list() # 重新排序或刷新

    # ---- 生命周期 ----
    def _on_close(self):
        self._update_cancel_event.set()
        self._destroy_update_progress_win()
        self.hotkey_listener.stop()
        self.root.destroy()

    def run(self):
        self.floating = FloatingWindow(self.root, VOCAB_PATH)

        def _on_hotkey_fail():
            self.root.after(0, lambda: self.status_var.set(f"错误：快捷键 {self.hotkey_var.get()} 注册失败，可能被占用"))

        self.hotkey_listener.start(on_register_fail=_on_hotkey_fail)
        self.status_var.set(f"已开启 — 划词后按 {self.hotkey_var.get()} 即可翻译")
        self.root.after(150, self._ensure_api_settings)
        self.root.after(1200, self._check_for_updates_async)
        self.root.mainloop()

if __name__ == "__main__":
    UnifiedApp().run()
