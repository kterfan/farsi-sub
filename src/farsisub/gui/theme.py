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
CONTROL_HEIGHT = 36  # buttons, inputs and combo boxes all line up on this
ICON = 18            # the one icon size inside a control
RADIUS_SM = 6     # chips, checkboxes, small tags
RADIUS = 10       # inputs, buttons, table cells
RADIUS_LG = 16    # cards and anything that frames a whole area
MOTION_MS = 160

# The second stop of the brand gradient, after the accent.
ACCENT_2 = "#8B5CF6"


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
    # Tinted backgrounds for the same meanings: a selected row, a status
    # pill, a chip. A solid accent band made the text on it hard to read and
    # forced a second set of "on blue" colours for every warning.
    accent_soft: str
    ok_soft: str
    warn_soft: str
    danger_soft: str


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
    accent_soft="#1A2A47",
    ok_soft="#10302A",
    warn_soft="#3A2A10",
    danger_soft="#3D1820",
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
    accent_soft="#E3ECFF",
    ok_soft="#DCFCE7",
    warn_soft="#FEF3C7",
    danger_soft="#FEE2E2",
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


def tokens_for(widget) -> Palette:
    """The palette a widget is actually drawn in.

    The editor stays light while the main window may be dark, so a painted
    widget cannot just read `active`: it asks the window it lives in.
    """
    node = widget
    while node is not None:
        tokens = getattr(node, "palette_tokens", None)
        if isinstance(tokens, Palette):
            return tokens
        node = node.parentWidget()
    return active


def font_stack() -> str:
    return f'"{FONT_FAMILY}", "{FONT_FALLBACK}"'


def elevate(widget, blur: int = 28, dy: int = 8, alpha: int | None = None) -> None:
    """A real drop shadow under a card.

    Qt style sheets cannot draw shadows, so the one piece of depth that is not
    a lighter surface is applied as a widget effect instead. On the light
    theme the same shadow read as a smudge, so it is much fainter there; call
    again after a theme switch.
    """
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    if alpha is None:
        alpha = 26 if active is LIGHT else 110
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
    Every control sits on CONTROL_HEIGHT, so a row of buttons, a combo box and
    a switch line up without anyone nudging them by hand.
    """
    from . import icons

    p = palette
    control = CONTROL_HEIGHT - 2  # the border is drawn inside the height
    chevron = icons.file("chevron-down", p.text_muted)
    arrow = (
        f'QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}'
        if chevron
        else ""
    )
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
    QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget,
    QWidget#Bare {{
        background: transparent;
    }}

    QLabel#Display {{ font-size: {FONT_DISPLAY}pt; font-weight: 800; }}
    QLabel#Heading {{ font-size: {FONT_HEADING}pt; font-weight: 700; }}
    QLabel#Title {{ font-size: {FONT_TITLE}pt; font-weight: 700; }}
    QLabel#Muted {{ color: {p.text_muted}; font-size: {FONT_SMALL}pt; }}
    QLabel#Caption {{
        color: {p.text_muted};
        font-size: {FONT_CAPTION}pt;
        font-weight: 600;
    }}
    QLabel#Clock {{
        color: {p.text_muted};
        font-size: {FONT_SMALL}pt;
        font-weight: 600;
    }}

    QFrame#Card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LG}px;
    }}
    /* A group's title sits above its card, not on the card's border. */
    QGroupBox {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS_LG}px;
        margin-top: {SPACE * 7}px;
        padding: {SPACE * 3}px;
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top right;
        right: {SPACE * 2}px;
        padding: 0 {SPACE}px;
        color: {p.text};
        background: transparent;
    }}
    QGroupBox QLabel, QGroupBox QCheckBox {{ font-weight: 400; }}
    QFrame#Divider {{ background: {p.border}; border: none; max-height: 1px; }}
    QFrame#VDivider {{
        background: {p.border};
        border: none;
        min-width: 1px;
        max-width: 1px;
        margin: {SPACE * 2}px {SPACE}px;
    }}

    /* Chips: a small rounded tag that states one fact. The coloured ones
       carry their meaning in a tint, with the text in the full colour. */
    QLabel#Chip, QToolButton#Chip {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: {RADIUS_SM + 4}px;
        padding: {SPACE}px {SPACE * 3}px;
        color: {p.text_muted};
        font-size: {FONT_CAPTION}pt;
        font-weight: 600;
    }}
    QLabel#ChipOk, QToolButton#ChipOk {{
        background: {p.ok_soft};
        border: 1px solid transparent;
        border-radius: {RADIUS_SM + 4}px;
        padding: {SPACE}px {SPACE * 3}px;
        color: {p.ok};
        font-size: {FONT_CAPTION}pt;
        font-weight: 700;
    }}
    QLabel#ChipWarn, QToolButton#ChipWarn {{
        background: {p.warn_soft};
        border: 1px solid transparent;
        border-radius: {RADIUS_SM + 4}px;
        padding: {SPACE}px {SPACE * 3}px;
        color: {p.warn};
        font-size: {FONT_CAPTION}pt;
        font-weight: 700;
    }}
    QToolButton#Chip, QToolButton#ChipOk, QToolButton#ChipWarn {{
        min-height: {CONTROL_HEIGHT - 10}px;
    }}
    QToolButton#ChipWarn:hover {{ border-color: {p.warn}; }}
    QToolButton#ChipOk:hover {{ border-color: {p.ok}; }}

    /* ---------------------------------------------------------- buttons
       QPushButton and QToolButton look the same: the icon buttons are tool
       buttons, the plain dialog buttons are push buttons, and the eye must
       not be able to tell which is which. */
    QPushButton, QToolButton {{
        background: {p.surface};
        border: 1px solid {p.border_strong};
        border-radius: {RADIUS}px;
        padding: 0 {SPACE * 4}px;
        min-height: {control}px;
        font-weight: 600;
        color: {p.text};
    }}
    QToolButton {{ padding: 0 {SPACE * 3}px; }}
    /* Widths are the button's own business (it measures its icon and
       label); the sheet only sets heights, colours and corners. */
    QToolButton[compact="true"] {{ padding: 0; }}
    QPushButton:hover, QToolButton:hover {{
        background: {p.hover};
        border-color: {p.text_muted};
    }}
    QPushButton:pressed, QToolButton:pressed {{ background: {p.pressed}; }}
    QPushButton:focus, QToolButton:focus {{ border: 1px solid {p.focus_ring}; }}
    QPushButton:disabled, QToolButton:disabled {{
        color: {p.text_muted};
        background: {p.surface_alt};
        border-color: {p.border};
    }}
    QToolButton:checked {{
        background: {p.accent_soft};
        border-color: {p.accent};
        color: {p.accent};
    }}

    QPushButton#Primary, QToolButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent}, stop:1 {ACCENT_2});
        color: {p.accent_text};
        border: 1px solid transparent;
        font-weight: 700;
        padding: 0 {SPACE * 5}px;
        min-height: {control}px;
    }}
    QPushButton#Primary:hover, QToolButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent_hover}, stop:1 #9D74F8);
    }}
    QPushButton#Primary:pressed, QToolButton#Primary:pressed {{
        background: {p.accent};
    }}
    QPushButton#Primary:focus, QToolButton#Primary:focus {{
        border: 1px solid {p.accent_text};
    }}
    QPushButton#Primary:disabled, QToolButton#Primary:disabled {{
        background: {p.surface_alt};
        color: {p.text_muted};
        border-color: {p.border};
    }}
    /* The empty-state button is the only thing on the page: it may be big. */
    QPushButton#Hero {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent}, stop:1 {ACCENT_2});
        color: {p.accent_text};
        border: none;
        font-size: {FONT_TITLE}pt;
        font-weight: 700;
        padding: 0 {SPACE * 8}px;
        min-height: {CONTROL_HEIGHT + 6}px;
        border-radius: {RADIUS + 2}px;
    }}
    QPushButton#Hero:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent_hover}, stop:1 #9D74F8);
    }}

    QPushButton#Quiet, QToolButton#Quiet {{
        background: transparent;
        border-color: transparent;
        color: {p.text_muted};
    }}
    QPushButton#Quiet:hover, QToolButton#Quiet:hover {{
        background: {p.hover};
        color: {p.text};
    }}
    QPushButton#Quiet:disabled, QToolButton#Quiet:disabled {{
        background: transparent;
        border-color: transparent;
        color: {p.border_strong};
    }}
    QPushButton#Danger, QToolButton#Danger {{
        color: {p.danger};
        background: transparent;
        border-color: transparent;
    }}
    QPushButton#Danger:hover, QToolButton#Danger:hover {{
        background: {p.danger_soft};
        border-color: {p.danger_soft};
    }}
    QPushButton#Danger:disabled, QToolButton#Danger:disabled {{
        background: transparent;
        border-color: transparent;
        color: {p.border_strong};
    }}

    /* A round button: the play control under the picture. */
    QToolButton#Round {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent}, stop:1 {ACCENT_2});
        border: none;
        border-radius: {(CONTROL_HEIGHT + 6) // 2}px;
        min-width: {CONTROL_HEIGHT + 6}px;
        max-width: {CONTROL_HEIGHT + 6}px;
        min-height: {CONTROL_HEIGHT + 6}px;
        max-height: {CONTROL_HEIGHT + 6}px;
        padding: 0;
    }}
    QToolButton#Round:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent_hover}, stop:1 #9D74F8);
    }}
    QToolButton#Round:disabled {{ background: {p.surface_alt}; }}

    /* A segment: related commands share one rounded frame, like the groups
       in a modern editor's command bar. The buttons inside are flat. */
    QFrame#Segment {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: {RADIUS + 2}px;
    }}
    QFrame#Segment QToolButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS - 2}px;
        min-height: {control - 6}px;
        padding: 0 {SPACE * 3}px;
    }}

    QFrame#Segment QToolButton:hover {{ background: {p.hover}; }}
    QFrame#Segment QToolButton:pressed {{ background: {p.pressed}; }}
    QFrame#Segment QToolButton:focus {{ border-color: {p.focus_ring}; }}
    QFrame#Segment QToolButton:disabled {{
        background: transparent;
        color: {p.border_strong};
    }}

    QToolBar {{ background: transparent; border: none; spacing: {SPACE}px; }}

    /* ----------------------------------------------------------- inputs */
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background: {p.surface};
        border: 1px solid {p.border_strong};
        border-radius: {RADIUS}px;
        padding: 0 {SPACE * 3}px;
        min-height: {control}px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QComboBox {{ padding-left: {SPACE * 8}px; min-width: 96px; }}
    QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {p.text_muted};
    }}
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
        border: 1px solid {p.focus_ring};
    }}
    QComboBox:disabled, QLineEdit:disabled {{
        color: {p.text_muted};
        background: {p.surface_alt};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 28px;
        subcontrol-origin: padding;
        subcontrol-position: center left;
    }}
    {arrow}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px;
        selection-background-color: {p.accent_soft};
        selection-color: {p.text};
    }}
    /* Inside a table cell the editor must not add a second frame. */
    QTableWidget QLineEdit {{
        border-radius: {RADIUS_SM}px;
        min-height: 0;
        padding: 0 {SPACE}px;
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
        background: {p.surface};
    }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}

    /* ----------------------------------------------------------- tables
       The selected row is a tint, not a solid band: the text keeps its own
       colour, and so do the warnings drawn into it. */
    QTableWidget, QListWidget {{
        background: transparent;
        border: none;
        gridline-color: transparent;
        selection-background-color: {p.accent_soft};
        selection-color: {p.text};
        alternate-background-color: {p.surface_alt};
    }}
    QTableWidget::item, QListWidget::item {{
        padding: {SPACE}px {SPACE * 2}px;
        border-bottom: 1px solid {p.border};
    }}
    QTableWidget::item:hover, QListWidget::item:hover {{ background: {p.hover}; }}
    QTableWidget::item:selected, QListWidget::item:selected {{
        background: {p.accent_soft};
        color: {p.text};
    }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        background: transparent;
        color: {p.text_muted};
        border: none;
        border-bottom: 1px solid {p.border_strong};
        padding: {SPACE * 2}px {SPACE * 3}px;
        font-size: {FONT_CAPTION}pt;
        font-weight: 700;
    }}
    QTableCornerButton::section {{ background: transparent; border: none; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {p.border_strong};
        border-radius: 3px;
        min-height: 36px;
        min-width: 36px;
    }}
    QScrollBar::handle:hover {{ background: {p.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSlider {{ background: transparent; min-height: 20px; }}
    QSlider::groove:horizontal {{
        background: {p.border};
        border: none;
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {ACCENT_2});
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: #FFFFFF;
        border: 3px solid {p.accent};
        width: 10px;
        height: 10px;
        margin: -6px 0;
        border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ border-color: {p.accent_hover}; }}

    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: {SPACE * 3}px; }}
    QSplitter::handle:vertical {{ height: {SPACE * 3}px; }}
    QSplitter::handle:hover {{ background: {p.accent_soft}; border-radius: 4px; }}

    QProgressBar {{
        background: {p.surface_alt};
        border: none;
        border-radius: 3px;
        max-height: 6px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {ACCENT_2});
        border-radius: 3px;
    }}
    /* The bar inside a queue row: tall enough to carry its percentage. */
    QProgressBar#RowProgress {{
        background: {p.border};
        margin: 15px 12px;
        border-radius: 3px;
    }}

    /* Idle it is just the card; the dashed outline is feedback for a drag
       in flight, not permanent decoration. */
    QFrame#DropZoneIdle {{ background: transparent; border: none; }}
    QFrame#DropZoneActive {{
        background: {p.accent_soft};
        border: 2px dashed {p.accent};
        border-radius: {RADIUS_LG}px;
    }}
    QToolTip {{
        background: {p.raised};
        color: {p.text};
        border: 1px solid {p.border_strong};
        border-radius: {RADIUS_SM}px;
        padding: {SPACE * 2}px {SPACE * 3}px;
    }}
    QMenu {{
        background: {p.raised};
        border: 1px solid {p.border};
        border-radius: {RADIUS}px;
        padding: {SPACE}px;
    }}
    QMenu::item {{ padding: {SPACE * 2}px {SPACE * 4}px; border-radius: {RADIUS_SM}px; }}
    QMenu::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
    QMenu::separator {{ height: 1px; background: {p.border}; margin: {SPACE}px {SPACE * 2}px; }}
    """
