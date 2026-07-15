# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules

datas = [('C:\\Users\\arsen\\Projects\\ac-copilot-trainer\\assets\\setups\\_schema', 'assets/setups/_schema'), ('C:\\Users\\arsen\\Projects\\ac-copilot-trainer\\src\\ac_copilot_trainer\\content\\fonts', 'fonts')]
binaries = []
hiddenimports = ['tools.ai_sidecar.voice.engine', 'tools.ai_sidecar.voice.playback', 'numpy', 'sounddevice', 'pyttsx3', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5', 'serial', 'serial.tools.list_ports', 'rtmixer', 'pa_ringbuffer']
datas += collect_data_files('tools.ai_sidecar')
datas += collect_data_files('_sounddevice_data')
binaries += collect_dynamic_libs('sounddevice')
binaries += collect_dynamic_libs('rtmixer')
binaries += collect_dynamic_libs('pa_ringbuffer')
hiddenimports += collect_submodules('tools.ai_sidecar')
hiddenimports += collect_submodules('tools.rig_launcher')


a = Analysis(
    ['C:\\Users\\arsen\\Projects\\ac-copilot-trainer\\tools\\rig_launcher\\__main__.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['C:\\Users\\arsen\\Projects\\ac-copilot-trainer\\build\\pyi_rth_ac_copilot_build_info.py'],
    excludes=[],
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
    name='AC-Copilot-Game-Point',
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
)
