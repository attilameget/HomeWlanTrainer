# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows steadyGrind onedir build."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"
WEB = SRC / "steadygrind" / "web"
ICON = ROOT / "deploy" / "windows" / "AppIcon.ico"

datas = [(str(WEB), "steadygrind/web")]
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "garminconnect",
    "zeroconf",
    "multipart",
    "webview",
    "pystray",
    "PIL",
    "steadygrind.windows_agent",
    "steadygrind.windows_bootstrap",
    "steadygrind.windows_startup",
    "steadygrind.windows_webview",
]

for pkg in ("uvicorn", "garminconnect", "zeroconf", "bleak", "fit_tool", "webview", "pystray"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("steadygrind")

exe_kwargs = dict(
    exclude_binaries=True,
    name="steadyGrind",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
if ICON.is_file():
    exe_kwargs["icon"] = str(ICON)

a = Analysis(
    [str(SRC / "steadygrind" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["AppKit", "Foundation", "WebKit", "PyObjCTools"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], **exe_kwargs)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="steadyGrind",
)
