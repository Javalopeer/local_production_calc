# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Include qtawesome fonts (icon rendering won't work without them)
qtawesome_datas = collect_data_files('qtawesome')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('data', 'data'),
        *qtawesome_datas,
    ],
    hiddenimports=[
        # openpyxl internals PyInstaller commonly misses
        'et_xmlfile',
        'openpyxl.cell._writer',
        'openpyxl.styles.stylesheet',
        'openpyxl.styles.fills',
        'openpyxl.styles.fonts',
        'openpyxl.styles.borders',
        'openpyxl.styles.alignment',
        'openpyxl.styles.protection',
        'openpyxl.worksheet.table',
        'openpyxl.worksheet.filters',
        'openpyxl.worksheet.datavalidation',
        'openpyxl.chart',
        'openpyxl.chart.chartspace',
        'openpyxl.drawing.image',
        # PySide6 extras needed by qtawesome SVG icons
        'PySide6.QtSvg',
        'PySide6.QtXml',
        # qtawesome
        'qtawesome',
        # app internal modules that may be missed due to dynamic imports
        'sync.app_config',
        'sync.app_logger',
        'sync.sharepoint_sync',
        'sync.downtime_approval',
        'sync.daily_performance',
        'sync.teams_notify',
        'sync.cleanup',
        'sync.safety_backup',
        'sync.clipboard_import',
        'sync.case_scraper',
        'tabs.tab_register',
        'tabs.tab_production',
        'tabs.tab_history',
        'tabs.tab_standards',
        'tabs.tab_dashboard',
        'tabs.tab_sync',
        'tabs.tab_theme_config',
        'tabs.tab_overtime',
        'tabs.downtime_manager',
        'tabs.breaks_dialog',
        'tabs.performance_popups',
        'tabs.clipboard_import_ui',
        'tabs.theme_table_utils',
        'tabs.utils',
        'tabs.widgets',
        'db.database',
        'self_installer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'scipy', 'numpy', 'PyQt5', 'tkinter',
        'pytest', 'sqlalchemy', 'pandas',
        'pptx', 'selenium', 'reportlab',
    ],
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
    name='ProductionCalcApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['data\\app_icon.ico'],
)
