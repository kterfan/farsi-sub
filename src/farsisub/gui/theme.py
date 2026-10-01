"""Design tokens and the Qt stylesheet built from them.

Colours live here and nowhere else. A hard-coded hex inside a widget is how a
theme quietly stops being a theme.
"""

from __future__ import annotations

from dataclasses import dataclass

FONT_FAMILY = "Vazirmatn"
FONT_FALLBACK = "Segoe UI"

# Type scale, in points. A flat interface where everything is one size reads
# as unfinished, so the steps here are wide enough to be seen at a glance.
# Persian also needs more vertical room than Latin: the widgets pay for that
# with padding rather than with a smaller face.
FONT_CAPTION = 9
FONT_SMALL = 10
FONT_BODY = 11
FONT_TITLE = 13
FONT_HEADING = 17
FONT_DISPLAY = 21

SPACE = 4  # every margin and gap is a multiple of this
ROW_HEIGHT = 36
RADIUS_SM = 6     # chips, checkboxes, small tags
RADIUS = 10       # inputs, buttons, table cells
RADIUS_LG = 16    # cards and anything that frames a whole area
MOTION_MS = 160


@dataclass(frozen=True)
class Palette:
    """A four-step surface scale.

    On a dark interface depth cannot come from shadow -- it disappears into
    the background. It comes from surfaces getting lighter as they rise, which
    is why `background`, `surface`, `surface_alt` and `raised` must stay
    distinguishable from each other.
    """

    background: str
    surface: str
    surface_alt: str
    raised: str
    border: str
    border_strong: str
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
    # Interaction states. Qt has no box-shadow, so depth has to come from a
    # hover tint and a visible focus ring instead.
    hover: str
    pressed: str
    focus_ring: str
    accent_hover: str


DARK = Palette(
    # A desaturated near-black reads as neutral instead of "navy app", and
    # leaves room for three lighter steps above it.
    background="#0B0E13",
    surface="#12161D",
    surface_alt="#171C25",
    raised="#1E242E",
    border="#232A35",
    border_strong="#333D4C",
    text="#E7ECF3",
    text_muted="#93A0B4",
    accent="#4C8DFF",
    accent_text="#FFFFFF",
    warn="#F5A524",
    danger="#F5576C",
    keyword="#A78BFA",
    ok="#2DD4A7",
    hover="#1B212B",
    pressed="#232A35",
    focus_ring="#4C8DFF",
    accent_hover="#6BA1FF",
)

LIGHT = Palette(
    background="#F6F7F9",
    surface="#FFFFFF",
    surface_alt="#F1F4F8",
    raised="#FFFFFF",
    border="#E3E8EF",
    border_strong="#CBD5E1",
    text="#0F172A",
    text_muted="#475569",
    accent="#2563EB",
    accent_text="#FFFFFF",
    warn="#B45309",
    danger="#B91C1C",
    keyword="#6D28D9",
    ok="#15803D",
    hover="#EEF2F7",
    pressed="#E2E8F0",
    focus_ring="#2563EB",
    accent_hover="#1D4ED8",
)


# The palette the main window is drawn in right now; painted widgets read it
# so a theme switch reaches them too.
active: Palette = DARK


def palette_for(name: str) -> Palette:
    return LIGHT if name == "light" else DARK


def apply(app, name: str) -> Palette:
    """Switch the whole application to the named theme."""
    global active
    active = palette_for(name)
    app.setStyleSheet(stylesheet(active))
    return active


def font_stack() -> str:
    return f'"{FONT_FAMILY}", "{FONT_FALLBACK}"'


def elevate(widget, blur: int = 28, dy: int = 8, alpha: int = 110) -> None:
    """A real drop shadow under a card.

    Qt style sheets cannot draw shadows, so the one piece of depth that is not
    a lighter surface is applied as a widget effect instead.
    """
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


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
    """One sheet for the whole app.

    Depth comes from the surface scale, weight from the type scale, and colour
    is spent on exactly one thing: the action the user is meant to take next.
    """
    p = palette
    return f"""
    * {{
        font-family: {font_stack()};
        font-size: {FONT_BODY}pt;
        outline: none;
    }}
    QWidget {{ background: {p.background}; color: {p.text}; }}
    QDialog, QMainWindow {{ background: {p.background}; }}
    QLabel {{ background: transparent; }}
    /* Containers must not paint the page colour on top of the card they sit
       in -- that is what put a dark rectangle inside the work surface. */
    QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}

    QLabel#Display {{ font-size: {FONT_DISPLAY}pt; font-weight: 700; }}
    QLabel#Heading {{ font-size: {FONT_HEADING}pt; font-weight: 700; }}
    QLabel#Muted {{ color: {p.text_muted}; font-size: {FONT_SMALL}pt; }}
    QLabel#Caption {{
        color: {p.text_muted};
        font-size: {FONT_CAPTION}pt;
        font-weight: 600;
    }}

    QFrame#Card, QGroupBox {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LG}px;
    }}
    QFrame#Divider {{ background: {p.border}; border: none; max-height: 1px; }}
    QLabel#Chip {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS_SM}px;
        padding: {SPACE}px {SPACE * 2}px;
        color: {p.text_muted};
        font-size: {FONT_CAPTION}pt;
    }}
    QLabel#ChipOk {{
        background: {p.surface_alt};
        border: 1px solid {p.ok};
        border-radius: {RADIUS_SM}px;
        padding: {SPACE}px {SPACE * 2}px;
        color: {p.ok};
        font-size: {FONT_CAPTION}pt;
        font-weight: 600;
    }}

    QPushButton {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE * 2}px {SPACE * 4}px;
        min-height: {ROW_HEIGHT - 12}px;
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {p.raised}; border-color: {p.border_strong}; }}
    QPushButton:pressed {{ background: {p.pressed}; }}
    QPushButton:focus {{ border: 1px solid {p.focus_ring}; }}
    QPushButton:disabled {{ color: {p.text_muted}; background: {p.surface}; }}
    QPushButton#Primary {{
        background: {p.accent};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-size: {FONT_TITLE}pt;
        font-weight: 700;
        padding: {SPACE * 2}px {SPACE * 6}px;
        min-height: {ROW_HEIGHT - 6}px;
    }}
    QPushButton#Primary:hover {{
        background: {p.accent_hover};
        border-color: {p.accent_hover};
    }}
    QPushButton#Primary:disabled {{
        background: {p.surface_alt};
        color: {p.text_muted};
        border-color: {p.border};
    }}
    QPushButton#Quiet {{
        background: transparent;
        border-color: transparent;
        color: {p.text_muted};
    }}
    QPushButton#Quiet:hover {{ background: {p.surface_alt}; color: {p.text}; }}
    QPushButton#Danger {{ color: {p.danger}; }}
    QPushButton#Danger:hover {{ background: {p.hover}; border-color: {p.danger}; }}

    QToolBar {{ background: transparent; border: none; spacing: {SPACE}px; }}
    QToolBar::separator {{
        background: {p.border};
        width: 1px;
        margin: {SPACE}px {SPACE * 2}px;
    }}
    QToolButton {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px {SPACE * 2}px;
    }}
    QToolButton:hover {{ background: {p.raised}; }}

    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px {SPACE * 2}px;
        min-height: {ROW_HEIGHT - 14}px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QComboBox:hover, QLineEdit:hover {{ border-color: {p.border_strong}; }}
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
        border: 1px solid {p.focus_ring};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}

    QCheckBox, QRadioButton {{
        background: transparent;
        spacing: {SPACE * 2}px;
        padding: {SPACE}px 0;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1px solid {p.border_strong};
        border-radius: {RADIUS_SM}px;
        background: {p.surface_alt};
    }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}

    QTableWidget, QListWidget {{
        background: transparent;
        border: none;
        gridline-color: transparent;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
        alternate-background-color: {p.surface_alt};
    }}
    QTableWidget::item, QListWidget::item {{ padding: {SPACE}px {SPACE * 2}px; }}
    QTableWidget::item:hover, QListWidget::item:hover {{ background: {p.hover}; }}
    QTableWidget::item:selected, QListWidget::item:selected {{
        background: {p.accent};
        color: {p.accent_text};
    }}
    QHeaderView::section {{
        background: transparent;
        color: {p.text_muted};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: {SPACE * 2}px;
        font-size: {FONT_CAPTION}pt;
        font-weight: 700;
    }}
    QTableCornerButton::section {{ background: transparent; border: none; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {p.border_strong};
        border-radius: 5px;
        min-height: 36px;
        min-width: 36px;
    }}
    QScrollBar::handle:hover {{ background: {p.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSlider::groove:horizontal {{
        background: {p.surface_alt};
        border: none;
        height: 6px;
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: {p.accent};
        border: 2px solid {p.surface};
        width: 14px;
        height: 14px;
        margin: -6px 0;
        border-radius: 9px;
    }}
    QSlider::handle:horizontal:hover {{ background: {p.accent_hover}; }}

    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: {SPACE * 2}px; }}
    QSplitter::handle:vertical {{ height: {SPACE * 2}px; }}
    QSplitter::handle:hover {{ background: {p.border}; }}

    QProgressBar {{
        background: {p.surface_alt};
        border: none;
        border-radius: 3px;
        max-height: 6px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}

    /* Idle it is just the card; the dashed outline is feedback for a drag
       in flight, not permanent decoration. */
    QFrame#DropZoneIdle {{ background: transparent; border: none; }}
    QFrame#DropZoneActive {{
        background: {p.surface_alt};
        border: 2px dashed {p.accent};
        border-radius: {RADIUS_LG}px;
    }}
    QToolTip {{
        background: {p.raised};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px {SPACE * 2}px;
    }}
    QMenu {{
        background: {p.raised};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px;
    }}
    QMenu::item {{ padding: {SPACE}px {SPACE * 3}px; border-radius: {RADIUS_SM}px; }}
    QMenu::item:selected {{ background: {p.accent}; color: {p.accent_text}; }}
    """
