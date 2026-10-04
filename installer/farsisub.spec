# PyInstaller build for FarsiSub.
#
#   .venv\Scripts\pyinstaller installer\farsisub.spec --noconfirm
#
# onedir, not onefile: the engine folder alone is over a gigabyte with the
# NVIDIA libraries, and unpacking that into a temp folder on every launch would
# make the app take a minute to start.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
BLOCK_CIPHER = None

datas = [
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
    (str(ROOT / "assets" / "brand"), "assets/brand"),
    # The engine: whisper-cli, its backends, and the VAD model.
    (str(ROOT / "bin"), "bin"),
]
# hazm ships word lists it reads at runtime.
datas += collect_data_files("hazm")

hiddenimports = [
    "av",
    "numpy",
    "hazm",
    "farsisub",
]
hiddenimports += collect_submodules("farsisub")

# Qt is huge; none of these are used and they add hundreds of megabytes.
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtSql",
    "matplotlib",
    "tkinter",
    "scipy",
    "pandas",
    "torch",
    "transformers",
    "IPython",
    "pytest",
    # Only the model conversion tool needs these, and that runs in its own
    # virtualenv, never inside the app.
    "huggingface_hub",
    "hf_xet",
    "requests",
]

# Windows shows these under the exe's Properties > Details.
import re

VERSION = re.search(
    r'__version__ = "([^"]+)"', (ROOT / "src" / "farsisub" / "__init__.py").read_text("utf-8")
).group(1)


def _version_file() -> str:
    """The VSVersionInfo text PyInstaller reads, written out by hand.

    Built as text rather than with PyInstaller's classes: their module only
    imports on Windows, and this keeps the spec checkable anywhere.
    """
    numbers = tuple(int(n) for n in (VERSION.split(".") + ["0"] * 4)[:4])
    strings = [
        ("CompanyName", "Erfan Esmailzadeh"),
        ("FileDescription", "FarsiSub - Persian subtitles from video"),
        ("FileVersion", VERSION),
        ("InternalName", "FarsiSub"),
        ("LegalCopyright", "© Erfan Esmailzadeh (عرفان اسمعیل‌زاده) · MIT"),
        ("OriginalFilename", "FarsiSub.exe"),
        ("ProductName", "FarsiSub"),
        ("ProductVersion", VERSION),
        ("Comments", "https://github.com/kterfan/farsi-sub"),
    ]
    entries = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
          {entries}
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    target = ROOT / "build" / "version_info.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)


a = Analysis(
    [str(ROOT / "installer" / "farsisub_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# The engine folder is shipped whole as data. PyInstaller also follows the DLL
# dependencies inside it and copies them next to the executable, which
# duplicated half a gigabyte of NVIDIA libraries. One copy is enough.
engine_files = {path.name.lower() for path in (ROOT / "bin").glob("*")}


def _keep(entry) -> bool:
    dest = Path(entry[0])
    if dest.parts and dest.parts[0].lower() == "bin":
        return True  # the engine's own copy stays
    return dest.name.lower() not in engine_files


a.binaries = [entry for entry in a.binaries if _keep(entry)]

pyz = PYZ(a.pure, a.zipped_data, cipher=BLOCK_CIPHER)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FarsiSub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # a GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "brand" / "farsisub.ico"),
    version=_version_file(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FarsiSub",
)
