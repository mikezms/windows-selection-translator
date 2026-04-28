"""UI 主题：颜色、字体、按钮 hover 辅助。基于 Tailwind slate/indigo 调色板。"""
import tkinter as tk

# === 背景 / 卡片 ===
UI_BG = "#f8fafc"           # 整体背景（slate-50）
UI_BG_ALT = "#f1f5f9"       # 次级背景（slate-100）
UI_CARD = "#ffffff"
UI_BORDER = "#e2e8f0"       # slate-200
UI_BORDER_SOFT = "#f1f5f9"  # slate-100
UI_LOG_BG = "#fafbfc"
UI_STATUS_BG = "#f1f5f9"

# === 文字 ===
UI_TEXT = "#0f172a"         # slate-900
UI_TEXT_SOFT = "#334155"    # slate-700
UI_TEXT_MUTED = "#64748b"   # slate-500

# === 主色（indigo） ===
UI_ACCENT = "#6366f1"       # indigo-500
UI_ACCENT_HOVER = "#4f46e5" # indigo-600
UI_ACCENT_DARK = "#4338ca"  # indigo-700
UI_CHIP = "#eef2ff"         # indigo-50

# === 语义色 ===
UI_OK = "#10b981"           # emerald-500
UI_OK_HOVER = "#059669"
UI_WARN = "#f59e0b"         # amber-500
UI_WARN_HOVER = "#d97706"
UI_DANGER = "#ef4444"       # red-500
UI_DANGER_HOVER = "#dc2626"
UI_INFO = "#0ea5e9"         # sky-500
UI_INFO_HOVER = "#0284c7"

# === 悬浮窗专用（极简亮色） ===
UI_FLOAT_BG = "#ffffff"     
UI_FLOAT_BG_SOFT = "#e2e8f0"
UI_FLOAT_FG = "#0f172a"
UI_FLOAT_MUTED = "#64748b"  
UI_FLOAT_ACCENT = "#2563eb" # 释义蓝色
UI_FLOAT_EXAMPLE = "#334155"
UI_FLOAT_BTN = "#0f172a"
UI_FLOAT_BTN_H = "#1e293b"

# === 生词本专用 ===
UI_MEANING = "#059669"      # emerald-600
UI_KEYWORD = "#4f46e5"
UI_ZH = "#0d9488"           # teal-600

FONT_FAMILY = "Microsoft YaHei UI"


def hover_bind(widget: tk.Widget, bg: str, hover_bg: str,
               fg: str | None = None, hover_fg: str | None = None) -> None:
    """给按钮加 hover 颜色切换。"""
    def on_enter(_):
        widget.configure(bg=hover_bg)
        if hover_fg:
            widget.configure(fg=hover_fg)

    def on_leave(_):
        widget.configure(bg=bg)
        if fg:
            widget.configure(fg=fg)

    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)
