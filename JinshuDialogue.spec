# -*- mode: python ; coding: utf-8 -*-
"""Windows x64 folder build; run through scripts/build.ps1."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, copy_metadata

ROOT = Path(SPECPATH).resolve()
datas = [
    (str(ROOT / 'src' / 'agent.js'), 'src'),
    (str(ROOT / 'src' / 'theme.qss'), 'src'),
    (str(ROOT / 'assets'), 'assets'),
    (str(ROOT / 'profiles'), 'profiles'),
]
for distribution in ('frida', 'PySide6-Essentials', 'shiboken6'):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(ROOT / 'src' / 'gui.py')],
    pathex=[str(ROOT / 'src')],
    binaries=collect_dynamic_libs('frida'),
    datas=datas,
    hiddenimports=['frida._frida', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'capstone', 'pefile', 'PyQt5', 'PyQt6', 'PySide2',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore',
        'PySide6.QtPdf', 'PySide6.QtMultimedia', 'PySide6.QtTest',
    ],
    noarchive=False,
    optimize=0,
)

# Qt's GUI hook discovers plugins for every installed image format. This app
# uses Core/Gui/Widgets and SVG only; keep that scope explicit (not QtPdf/QML).
qt_dlls = {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll', 'qt6svg.dll'}
qt_plugins = {'qwindows.dll', 'qoffscreen.dll', 'qmodernwindowsstyle.dll',
              'qico.dll', 'qjpeg.dll', 'qgif.dll', 'qsvg.dll', 'qsvgicon.dll'}
def needed_binary(entry):
    destination = entry[0].replace('\\', '/').lower()
    name = destination.rsplit('/', 1)[-1]
    # Qt's Windows build imports unversioned ucnv_* symbols from OS ICU.
    # A Python runtime can carry another icuuc.dll exporting *_78 instead;
    # bundling that DLL shadows Windows ICU and makes QtCore fail to load.
    if name == 'icuuc.dll':
        return False
    if destination.startswith('pyside6/plugins/'):
        return name in qt_plugins
    if destination.startswith('pyside6/') and name.startswith('qt6') and name.endswith('.dll'):
        return name in qt_dlls
    return True

a.binaries = [entry for entry in a.binaries if needed_binary(entry)]
pyz = PYZ(a.pure)
icon_path = ROOT / 'assets' / 'app.ico'
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JinshuDialogue',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path) if icon_path.is_file() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='JinshuDialogue')
