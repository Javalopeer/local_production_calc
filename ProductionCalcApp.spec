# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Production Performance Calculator
Build command (run from the local_production_calc folder):
    pyinstaller ProductionCalcApp.spec
Output: dist/ProductionCalcApp.exe
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Paths ──────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(SPEC))   # local_production_calc/

# ── Data files to bundle ───────────────────────────────────────────────────────
datas = [
    # App data files (standards, units, icon)
    (os.path.join(HERE, 'data', 'standards.json'), 'data'),
    (os.path.join(HERE, 'data', 'units_eq.json'),  'data'),
    (os.path.join(HERE, 'data', 'app_icon.ico'),   'data'),
]

# qtawesome fonts and icon data
datas += collect_data_files('qtawesome')

# openpyxl templates and data files
datas += collect_data_files('openpyxl')

# ── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'openpyxl',
    'openpyxl.styles',
    'openpyxl.utils',
    'openpyxl.drawing.image',
    'openpyxl.workbook',
    'openpyxl.writer',
    'openpyxl.reader',
    'openpyxl.formatting',
    'openpyxl.chart',
    'openpyxl.worksheet',
    'openpyxl.comments',
    'et_xmlfile',
    'sqlite3',
    'json',
    'winreg',
    # xml — required by openpyxl internally
    'xml',
    'xml.etree',
    'xml.etree.ElementTree',
    'xml.etree.ElementInclude',
    'xml.etree.cElementTree',
    # sync / sharepoint module
    'sync',
    'sync.app_config',
    'sync.sharepoint_sync',
    'sync.clipboard_import',
    'sync.case_scraper',
]
hiddenimports += collect_submodules('qtawesome')
hiddenimports += collect_submodules('openpyxl')

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(HERE, 'main.py')],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'PIL', 'tkinter',
        'unittest', 'pydoc', 'doctest', 'difflib',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ProductionCalcApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No black console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(HERE, 'data', 'app_icon.ico'),
)
