$ErrorActionPreference = "Stop"

$Python = "py -3"
if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
    $Python = "python"
}

Invoke-Expression "$Python -m pip install -r requirements.txt"
Invoke-Expression "$Python -m pip install pyinstaller"
Invoke-Expression "$Python -m PyInstaller .\SnapTranslate.spec --noconfirm --clean"

if (Get-Command ISCC.exe -ErrorAction SilentlyContinue) {
    ISCC.exe .\installer.iss
    Write-Host "Installer has been generated in the installer directory."
} else {
    Write-Host "PyInstaller finished. App directory: dist\SnapTranslate."
    Write-Host "To generate setup exe, install Inno Setup, make ISCC.exe available in PATH, then rerun this script."
}
