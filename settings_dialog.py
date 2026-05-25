"""API 设置弹窗。"""
from __future__ import annotations

import tkinter as tk
import threading
import webbrowser
from pathlib import Path
from tkinter import font as tkfont, messagebox
from tkinter import ttk

from PIL import Image, ImageTk

import app_config
import deepseek
from app_paths import resource_path
from ui_theme import (
    FONT_FAMILY,
    UI_ACCENT,
    UI_ACCENT_DARK,
    UI_BG,
    UI_BORDER,
    UI_CARD,
    UI_CHIP,
    UI_TEXT,
    UI_TEXT_MUTED,
    UI_TEXT_SOFT,
)


class ApiSettingsDialog:
    def __init__(self, parent: tk.Tk, *, first_run: bool = False):
        self.parent = parent
        self.first_run = first_run
        self.result = False
        self.config = app_config.load_config()

        self.win = tk.Toplevel(parent)
        self.win.title("API 设置")
        self.win.configure(bg=UI_BG)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self.provider_var = tk.StringVar(value=str(self.config.get("ai_provider") or "deepseek"))
        self.key_var = tk.StringVar(value=str(self.config.get("ai_api_key") or ""))
        self.base_url_var = tk.StringVar(value=str(self.config.get("ai_base_url") or ""))
        self.model_var = tk.StringVar(value=str(self.config.get("ai_model") or ""))
        self.hotkey_var = tk.StringVar(value=str(self.config.get("hotkey") or app_config.DEFAULT_HOTKEY))
        self.key_visible_var = tk.BooleanVar(value=False)
        self.saved_models_var = tk.StringVar(value="")
        self.saved_models = list(self.config.get("ai_models") or [])
        self._provider_icons = {}
        self._base_placeholder = "https://api.example.com/v1"

        self._build_ui()
        self._apply_provider_defaults(force_empty=False)
        self._refresh_saved_models_menu()
        self._center()
        self.win.wait_window()

    def _build_ui(self) -> None:
        outer = tk.Frame(self.win, bg=UI_BG, padx=22, pady=18)
        outer.pack(fill="both", expand=True)

        title = "首次使用需要配置 API" if self.first_run else "API 设置"
        tk.Label(
            outer, text=title, bg=UI_BG, fg=UI_TEXT,
            font=tkfont.Font(family=FONT_FAMILY, size=15, weight="bold"),
        ).pack(anchor="w")
        tk.Label(
            outer,
            text="AI 技术语境翻译和例句生成会使用这里的服务商配置。",
            bg=UI_BG, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(anchor="w", pady=(4, 14))

        card = tk.Frame(outer, bg=UI_CARD, highlightbackground=UI_BORDER, highlightthickness=1, padx=16, pady=14)
        card.pack(fill="x")

        provider_row = tk.Frame(card, bg=UI_CARD)
        provider_row.pack(fill="x", pady=(0, 10))
        self.provider_icon_label = tk.Label(provider_row, bg=UI_CARD)
        self.provider_icon_label.pack(side="left", padx=(0, 8))
        self._label(provider_row, "服务商").pack(side="left")
        values = list(app_config.PROVIDER_PRESETS.keys())
        labels = {k: app_config.PROVIDER_PRESETS[k]["label"] for k in values}
        self.provider_menu = tk.OptionMenu(
            provider_row,
            self.provider_var,
            *values,
            command=lambda _value: self._apply_provider_defaults(force_empty=True),
        )
        self.provider_menu.configure(
            bg=UI_CHIP, fg=UI_ACCENT, activebackground=UI_ACCENT,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            width=22,
        )
        menu = self.provider_menu["menu"]
        menu.configure(bg=UI_CARD, fg=UI_TEXT_SOFT, activebackground=UI_CHIP, activeforeground=UI_ACCENT)
        menu.delete(0, "end")
        for key in values:
            menu.add_command(label=labels[key], command=lambda k=key: self._select_provider(k))
        self.provider_menu.pack(side="right")

        key_row = self._entry(card, "API Key", self.key_var, show="*")
        key_row.pack(fill="x", pady=(0, 10))
        self.key_link = tk.Label(
            key_row, text="获取密钥", bg=UI_CARD, fg=UI_ACCENT,
            font=tkfont.Font(family=FONT_FAMILY, size=9, underline=True),
            cursor="hand2",
        )
        self.key_link.pack(anchor="e", pady=(4, 0))
        self.key_link.bind("<Button-1>", lambda _e: self._open_key_url())
        tk.Checkbutton(
            card, text="显示 Key", variable=self.key_visible_var,
            command=self._toggle_key_visibility,
            bg=UI_CARD, fg=UI_TEXT_MUTED, activebackground=UI_CARD,
            selectcolor=UI_CHIP, highlightthickness=0, bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9),
        ).pack(anchor="w", pady=(0, 10))
        self.base_url_row = self._entry(card, "Base URL", self.base_url_var)
        self.base_entry.bind("<FocusIn>", lambda _e: self._clear_placeholder())
        self.base_entry.bind("<FocusOut>", lambda _e: self._restore_placeholder())

        model_row = tk.Frame(card, bg=UI_CARD)
        model_row.pack(fill="x")
        self._label(model_row, "模型").pack(anchor="w", pady=(0, 4))
        model_line = tk.Frame(model_row, bg=UI_CARD)
        model_line.pack(fill="x")
        self.model_combo = ttk.Combobox(
            model_line, textvariable=self.model_var,
            values=[],
            font=tkfont.Font(family=FONT_FAMILY, size=10),
        )
        self.model_combo.pack(side="left", fill="x", expand=True, ipady=4)
        self.model_combo.bind("<FocusOut>", lambda _e: self._persist_manual_model())
        self.refresh_models_btn = tk.Button(
            model_line, text="获取模型", command=self._refresh_models,
            bg=UI_CARD, fg=UI_ACCENT, activebackground=UI_CHIP,
            activeforeground=UI_ACCENT, relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            padx=10, pady=5, cursor="hand2",
        )
        self.refresh_models_btn.pack(side="right", padx=(8, 0))

        hotkey_row = tk.Frame(card, bg=UI_CARD)
        hotkey_row.pack(fill="x", pady=(10, 0))
        self._label(hotkey_row, "快捷键").pack(side="left")
        tk.Entry(
            hotkey_row, textvariable=self.hotkey_var,
            bg="#ffffff", fg=UI_TEXT, insertbackground=UI_TEXT,
            relief="solid", bd=1, highlightthickness=0,
            font=tkfont.Font(family=FONT_FAMILY, size=10),
            width=20,
        ).pack(side="right")

        model_row = tk.Frame(card, bg=UI_CARD)
        model_row.pack(fill="x", pady=(10, 0))
        self._label(model_row, "已保存模型").pack(side="left")
        self.saved_model_menu = tk.OptionMenu(model_row, self.saved_models_var, "")
        self.saved_model_menu.configure(
            bg=UI_CHIP, fg=UI_ACCENT, activebackground=UI_ACCENT,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            width=26,
        )
        self.saved_model_menu.pack(side="right")

        model_btn_row = tk.Frame(card, bg=UI_CARD)
        model_btn_row.pack(fill="x", pady=(8, 0))
        tk.Button(
            model_btn_row, text="切换到所选模型", command=self._load_selected_model,
            bg=UI_CARD, fg=UI_ACCENT, activebackground=UI_CHIP,
            activeforeground=UI_ACCENT, relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            padx=12, pady=6, cursor="hand2",
        ).pack(side="left")

        btn_row = tk.Frame(outer, bg=UI_BG)
        btn_row.pack(fill="x", pady=(16, 0))
        if not self.first_run:
            tk.Button(
                btn_row, text="取消", command=self._on_close,
                bg=UI_CARD, fg=UI_TEXT_SOFT, activebackground=UI_CHIP,
                activeforeground=UI_ACCENT, relief="flat", bd=0,
                font=tkfont.Font(family=FONT_FAMILY, size=10),
                padx=18, pady=8, cursor="hand2",
            ).pack(side="right", padx=(8, 0))
        self.save_btn = tk.Button(
            btn_row, text="保存", command=self._save,
            bg=UI_ACCENT, fg="#ffffff", activebackground=UI_ACCENT_DARK,
            activeforeground="#ffffff", relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"),
            padx=20, pady=8, cursor="hand2",
        )
        self.save_btn.pack(side="right")

        self.test_btn = tk.Button(
            btn_row, text="测试连接", command=self._test_connection,
            bg=UI_CARD, fg=UI_ACCENT, activebackground=UI_CHIP,
            activeforeground=UI_ACCENT, relief="flat", bd=0,
            font=tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"),
            padx=18, pady=8, cursor="hand2",
        )
        self.test_btn.pack(side="right", padx=(0, 8))

    def _label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(
            parent, text=text, bg=UI_CARD, fg=UI_TEXT_MUTED,
            font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
        )

    def _entry(self, parent: tk.Widget, label: str, var: tk.StringVar, show: str = "") -> tk.Frame:
        row = tk.Frame(parent, bg=UI_CARD)
        self._label(row, label).pack(anchor="w", pady=(0, 4))
        ent = tk.Entry(
            row, textvariable=var, show=show,
            bg="#ffffff", fg=UI_TEXT, insertbackground=UI_TEXT,
            relief="solid", bd=1, highlightthickness=0,
            font=tkfont.Font(family=FONT_FAMILY, size=10),
            width=48,
        )
        ent.pack(fill="x", ipady=5)
        if label == "API Key":
            self.key_entry = ent
        if label == "Base URL":
            self.base_entry = ent
        return row

    def _select_provider(self, provider: str) -> None:
        self.provider_var.set(provider)
        self._apply_provider_defaults(force_empty=True)

    def _apply_provider_defaults(self, *, force_empty: bool) -> None:
        provider = self.provider_var.get()
        preset = app_config.PROVIDER_PRESETS.get(provider, app_config.PROVIDER_PRESETS["deepseek"])
        if provider == "custom":
            if force_empty:
                self.base_url_var.set("")
                self.model_var.set("")
        else:
            if force_empty or not self.base_url_var.get().strip() or self.base_url_var.get() == self._base_placeholder:
                self.base_url_var.set(preset["base_url"])
            if force_empty or not self.model_var.get().strip():
                self.model_var.set(preset["model"])
        self.provider_menu.configure(text=preset["label"])
        self._update_provider_icon(provider)
        self._update_base_url_visibility()
        self._update_key_link()
        self._update_model_values()

    def _toggle_key_visibility(self) -> None:
        self.key_entry.configure(show="" if self.key_visible_var.get() else "*")

    def _form_config(self) -> dict:
        provider = self.provider_var.get()
        base_url = self.base_url_var.get().strip()
        if base_url == self._base_placeholder:
            base_url = ""
        base_url = app_config.effective_base_url(provider, base_url)
        return {
            "ai_provider": provider,
            "ai_api_key": self.key_var.get().strip(),
            "ai_base_url": base_url,
            "ai_model": self.model_var.get().strip(),
            "hotkey": app_config.normalize_hotkey(self.hotkey_var.get()),
            "setup_done": True,
        }

    def _update_provider_icon(self, provider: str) -> None:
        icon = self._provider_icons.get(provider)
        if icon is None:
            filename = app_config.provider_preset(provider).get("icon") or "custom.png"
            path = Path(resource_path(f"image/providers/{filename}"))
            if path.exists():
                try:
                    with Image.open(path) as img:
                        img = img.convert("RGBA").resize((24, 24), Image.Resampling.LANCZOS)
                        icon = ImageTk.PhotoImage(img)
                except Exception:
                    icon = False
            else:
                icon = False
            self._provider_icons[provider] = icon
        if icon:
            self.provider_icon_label.configure(image=icon, width=26)
            self.provider_icon_label.image = icon
        else:
            self.provider_icon_label.configure(image="", width=0)
            self.provider_icon_label.image = None

    def _update_base_url_visibility(self) -> None:
        if app_config.is_official_provider(self.provider_var.get()):
            self.base_url_row.pack_forget()
        else:
            if not self.base_url_row.winfo_ismapped():
                self.base_url_row.pack(fill="x", pady=(0, 10), before=self.model_combo.master.master)
            self._restore_placeholder()

    def _clear_placeholder(self) -> None:
        if self.base_url_var.get() == self._base_placeholder:
            self.base_url_var.set("")
            self.base_entry.configure(fg=UI_TEXT)

    def _restore_placeholder(self) -> None:
        if app_config.is_official_provider(self.provider_var.get()):
            return
        if not self.base_url_var.get().strip():
            self.base_url_var.set(self._base_placeholder)
            self.base_entry.configure(fg=UI_TEXT_MUTED)
        else:
            self.base_entry.configure(fg=UI_TEXT)

    def _update_key_link(self) -> None:
        url = app_config.provider_preset(self.provider_var.get()).get("key_url") or ""
        if url:
            self.key_link.pack(anchor="e", pady=(4, 0))
        else:
            self.key_link.pack_forget()

    def _open_key_url(self) -> None:
        url = app_config.provider_preset(self.provider_var.get()).get("key_url") or ""
        if url:
            webbrowser.open(url)

    def _update_model_values(self, values: list[str] | None = None) -> None:
        models = values if values is not None else app_config.provider_models(self.provider_var.get())
        current = self.model_var.get().strip()
        if current and current not in models:
            models = [current] + list(models)
        self.model_combo.configure(values=list(dict.fromkeys(models)))

    def _persist_manual_model(self) -> None:
        value = self.model_var.get().strip()
        if not value:
            return
        values = list(self.model_combo.cget("values"))
        if value not in values:
            values.insert(0, value)
            self.model_combo.configure(values=values)

    def _refresh_models(self) -> None:
        cfg = self._form_config()
        self.refresh_models_btn.configure(state="disabled", text="获取中")

        def _worker() -> None:
            ok, result = deepseek.fetch_models(cfg)
            if not self.win.winfo_exists():
                return
            self.win.after(0, lambda: self._on_refresh_models_done(ok, result))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_refresh_models_done(self, ok: bool, result) -> None:
        self.refresh_models_btn.configure(state="normal", text="获取模型")
        if ok:
            models = list(result)
            self._update_model_values(models)
            if models and not self.model_var.get().strip():
                self.model_var.set(models[0])
            messagebox.showinfo("刷新成功", f"已获取 {len(models)} 个模型。", parent=self.win)
        else:
            messagebox.showerror("刷新失败", str(result), parent=self.win)

    def _saved_model_label(self, item: dict) -> str:
        model = str(item.get("model") or "").strip()
        base_url = str(item.get("base_url") or "").strip()
        provider = str(item.get("provider") or "custom")
        if not model:
            return ""
        label = model
        if base_url:
            label = f"{model} @ {base_url}"
        if provider and provider != "custom":
            label = f"{provider}: {label}"
        return label

    def _refresh_saved_models_menu(self) -> None:
        menu = self.saved_model_menu["menu"]
        menu.delete(0, "end")
        labels = [self._saved_model_label(item) for item in self.saved_models if self._saved_model_label(item)]
        if not labels:
            labels = ["暂无已保存模型"]
        for label in labels:
            menu.add_command(label=label, command=lambda v=label: self.saved_models_var.set(v))
        self.saved_models_var.set(labels[0])

    def _load_selected_model(self) -> None:
        selected = self.saved_models_var.get()
        for item in self.saved_models:
            if self._saved_model_label(item) == selected:
                self.provider_var.set(str(item.get("provider") or "custom"))
                self.base_url_var.set(str(item.get("base_url") or ""))
                self.model_var.set(str(item.get("model") or ""))
                self._apply_provider_defaults(force_empty=False)
                return

    def _test_connection(self) -> None:
        cfg = self._form_config()
        if not app_config.is_official_provider(cfg.get("ai_provider", "")):
            self.base_url_var.set(cfg["ai_base_url"])
        self.test_btn.configure(state="disabled", text="测试中...")

        def _worker() -> None:
            ok, msg = deepseek.test_connection(cfg)
            if not self.win.winfo_exists():
                return
            self.win.after(0, lambda: self._on_test_done(ok, msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str) -> None:
        self.test_btn.configure(state="normal", text="测试连接")
        if ok:
            messagebox.showinfo("测试成功", msg, parent=self.win)
        else:
            messagebox.showerror("测试失败", msg, parent=self.win)

    def _save(self) -> None:
        provider = self.provider_var.get()
        api_key = self.key_var.get().strip()
        base_url = self.base_url_var.get().strip()
        model = self.model_var.get().strip()
        if not api_key:
            messagebox.showwarning("提示", "请填写 API Key。", parent=self.win)
            return
        if not model:
            messagebox.showwarning("提示", "请填写模型名称。", parent=self.win)
            return
        if (not app_config.is_official_provider(provider)) and app_config.provider_kind(provider) == "openai_compatible" and (not base_url or base_url == self._base_placeholder):
            messagebox.showwarning("提示", "请填写 Base URL。", parent=self.win)
            return

        cfg = app_config.load_config()
        form_cfg = self._form_config()
        if not app_config.is_official_provider(provider):
            self.base_url_var.set(form_cfg["ai_base_url"])
        cfg.update(form_cfg)
        wrapped = app_config.append_model_history(
            {"ai_models": self.saved_models},
            form_cfg["ai_provider"],
            form_cfg["ai_base_url"],
            form_cfg["ai_model"],
        )
        self.saved_models = list(wrapped.get("ai_models") or [])
        cfg["ai_models"] = self.saved_models
        app_config.save_config(cfg)
        self.result = True
        self.win.destroy()

    def _on_close(self) -> None:
        if self.first_run and not app_config.is_ai_configured():
            self.result = False
        self.win.destroy()

    def _center(self) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        x = self.parent.winfo_rootx() + max(0, (self.parent.winfo_width() - w) // 2)
        y = self.parent.winfo_rooty() + max(0, (self.parent.winfo_height() - h) // 2)
        self.win.geometry(f"+{x}+{y}")
