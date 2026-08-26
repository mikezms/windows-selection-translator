# Repository Guidelines

## Project Structure & Module Organization

SnapTranslate is a Windows-only Python/Tkinter desktop application. `main.py` is the primary entry point and coordinates translation, vocabulary review, history, hotkeys, the floating window, and the tray icon. Keep integrations in focused modules: `translator.py` and `deepseek.py` handle remote services, `tts.py` handles speech, and `app_config.py`, `app_paths.py`, `history_store.py`, and `vocab_store.py` own configuration and persisted data. UI components live in `settings_dialog.py`, `floating_window.py`, `vocab_review.py`, and `tray_icon.py`. Static artwork belongs in `image/`; HTML mockups are prototypes, not runtime code. Treat `build/`, `dist/`, and `installer/` as generated output.

## Build, Test, and Development Commands

Run these commands from the repository root in PowerShell:

```powershell
py -3 -m pip install -r requirements.txt
py -3 main.py
py -3 -m compileall -q -x "venv|build|dist" .
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

The first command installs runtime dependencies. The second launches the app locally. `compileall` provides a fast syntax check. The build script installs PyInstaller, creates `dist\SnapTranslate\SnapTranslate.exe`, and also creates an Inno Setup installer when `ISCC.exe` is available.

## Coding Style & Naming Conventions

Use four-space indentation and follow PEP 8. Name modules, functions, and variables with `snake_case`, classes with `PascalCase`, and internal helpers with a leading underscore. Keep user-facing Chinese text consistent with the existing UI. Prefer small service modules over adding more responsibilities to `main.py`; keep Tkinter updates on the UI thread via `root.after(...)`. No formatter or linter is enforced, so keep imports grouped as standard library, third-party, then local modules.

## Testing Guidelines

There is currently no automated test suite or coverage threshold. Before submitting, run the syntax check and manually verify startup, `Ctrl+L` translation, clipboard handling, floating-window actions, settings, tray behavior, and vocabulary/history persistence on Windows. For new non-UI logic, add `pytest` tests under `tests/` named `test_<module>.py`. Set `SNAPTRANSLATE_DATA_DIR` to a temporary directory so tests never modify `%APPDATA%\SnapTranslate`.

## Commit & Pull Request Guidelines

Recent commits use short, action-led subjects such as `增加系统托盘菜单入口` and `优化 AI 接入层配置解析逻辑`; concise English imperatives are also acceptable. Keep each commit focused. Pull requests should explain behavior changes, list verification performed, link relevant issues, and include before/after screenshots for UI work. Release changes must keep `version.py`, `installer.iss`, and update metadata such as `latest.json` aligned.

## Security & Configuration

Never commit API keys, `settings.json`, or personal history. `api_key.txt` and `history.json` are intentionally ignored. Avoid logging secrets or full provider responses containing credentials.
