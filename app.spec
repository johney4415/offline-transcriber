# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: onedir build (NOT onefile - the 1.5GB model lives outside).
# Build on Windows with:  pyinstaller app.spec

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []

for pkg in ["ctranslate2", "av", "faster_whisper", "pypinyin", "tokenizers", "onnxruntime"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# opencc (pure python) ships its conversion dictionaries as data files
datas += collect_data_files("opencc")

a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "numpy.testing", "PIL", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OfflineTranscriber",
    debug=False,
    console=False,  # GUI app - no console window
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="OfflineTranscriber",
)
