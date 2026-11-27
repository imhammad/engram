# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Engram AI engine sidecar.
# Build with scripts/build-sidecar.sh rather than calling PyInstaller directly.
#
# Onefile: Tauri's externalBin bundles exactly one executable per target, so
# the engine is a single self-extracting binary (see docs/decisions/0004).
# Models are not bundled; they live in the app data directory (ADR 0003).
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for package in ("llama_cpp", "sqlcipher3", "sqlite_vec", "sentence_transformers", "faster_whisper", "pytesseract"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# Numbered schema migrations, read at startup from next to store.py.
datas += [("migrations/*.sql", "migrations")]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="engram-ai-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX corrupts macOS code signatures and saves little on these libraries.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
