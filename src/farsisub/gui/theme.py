"""Design tokens and the Qt stylesheet built from them.

Colours live here and nowhere else. A hard-coded hex inside a widget is how a
theme quietly stops being a theme.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FONT_FAMILY = "Vazirmatn"
FONT_FALLBACK = "Segoe UI"

# Type scale, in points. Persian needs more vertical room than Latin, hence the
# generous line height used in the widgets.
FONT_SMALL = 9
FONT_BODY = 10
FONT_TITLE = 12
FONT_HEADING = 15

SPACE = 4  # every margin and gap is a multiple of this
ROW_HEIGHT = 32
RADIUS = 6
MOTION_MS = 160


@dataclass(frozen=True)
class Palette:
    background: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_text: str
    # Meaning-carrying colours, always paired with an icon or underline in the
    # widgets so colour is never the only signal.
    warn: str  # low confidence
    danger: str  # very low confidence
    keyword: str
    ok: str


DARK = Palette(
    background="#0F172A",
    surface="#1A2234",
    surface_alt="#141C2E",
    border="rgba(255, 255, 255, 0.08)",
    text="#F1F5F9",
    text_muted="#94A3B8",
    accent="#38BDF8",
    accent_text="#04121F",
    warn="#F59E0B",
    danger="#EF4444",
    keyword="#A78BFA",
    ok="#22C55E",
)

LIGHT = Palette(
    background="#FFFFFF",
    surface="#F8FAFC",
    surface_alt="#F1F5F9",
    border="#E2E8F0",
    text="#0F172A",
    text_muted="#475569",
    accent="#0284C7",
    accent_text="#FFFFFF",
    warn="#B45309",
    danger="#B91C1C",
    keyword="#6D28D9",
    ok="#15803D",
)


def font_stack() -> str:
    return f'"{FONT_FAMILY}", "{FONT_FALLBACK}"'


def load_fonts() -> bool:
    """Register the bundled Persian font. Windows' default renders it badly."""
    from PySide6.QtGui import QFontDatabase

    from ..engine.locate import resource_dir

    assets = resource_dir() / "assets" / "fonts"
    loaded = False
    for path in sorted(assets.glob("Vazirmatn*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) != -1:
            loaded = True
    return loaded


def stylesheet(palette: Palette) -> str:
    p = palette
    return f"""
    * {{
        font-family: {font_stack()};
        font-size: {FONT_BODY}pt;
    }}
    QWidget {{
        background: {p.background};
        color: {p.text};
    }}
    QFrame#Card, QGroupBox {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
    }}
    QLabel#Heading {{
        font-size: {FONT_HEADING}pt;
        font-weight: 600;
    }}
    QLabel#Muted {{
        color: {p.text_muted};
        font-size: {FONT_SMALL}pt;
    }}
    QPushButton {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE * 2}px {SPACE * 4}px;
        min-height: {ROW_HEIGHT - 8}px;
    }}
    QPushButton:hover {{ background: {p.surface_alt}; }}
    QPushButton:disabled {{ color: {p.text_muted}; }}
    QPushButton#Primary {{
        background: {p.accent};
        color: {p.accent_text};
        border: none;
        font-weight: 600;
    }}
    QPushButton#Danger {{ color: {p.danger}; }}
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px {SPACE * 2}px;
        min-height: {ROW_HEIGHT - 10}px;
    }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QCheckBox {{ spacing: {SPACE * 2}px; padding: {SPACE}px 0; }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p.border};
        border-radius: 3px;
        background: {p.surface_alt};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
    QTableWidget, QListWidget {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        gridline-color: {p.border};
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
        alternate-background-color: {p.surface_alt};
    }}
    QTableWidget::item {{ padding: 0 {SPACE * 2}px; }}
    QHeaderView::section {{
        background: {p.surface_alt};
        color: {p.text_muted};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: {SPACE}px {SPACE * 2}px;
    }}
    QProgressBar {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        height: {SPACE * 5}px;
        text-align: center;
        color: {p.text};
    }}
    QProgressBar::chunk {{
        background: {p.accent};
        border-radius: {RADIUS - 2}px;
    }}
    QFrame#DropZone {{
        background: {p.surface_alt};
        border: 2px dashed {p.border};
        border-radius: {RADIUS * 2}px;
    }}
    QFrame#DropZoneActive {{
        background: {p.surface};
        border: 2px dashed {p.accent};
        border-radius: {RADIUS * 2}px;
    }}
    QToolTip {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        padding: {SPACE}px;
    }}
    """
