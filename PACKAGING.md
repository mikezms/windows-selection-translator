# SnapTranslate Packaging

## Build app folder

Run in PowerShell from the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

The runnable app folder is:

```text
dist\SnapTranslate\SnapTranslate.exe
```

## Build setup exe

Install Inno Setup and make sure `ISCC.exe` is available in `PATH`, then rerun:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

The setup exe will be generated under:

```text
installer\
```

## Runtime data

Installed builds write user data to:

```text
%APPDATA%\SnapTranslate\
  settings.json
  vocab.json
  history.json
```

On first run, the app opens the API settings dialog. Users can choose DeepSeek,
OpenAI, Gemini, or an OpenAI-compatible proxy endpoint.
