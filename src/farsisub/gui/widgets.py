"""Building blocks shared by the windows: buttons, rows that wrap, switches.

The rule they all serve: no command is ever out of reach. A toolbar hid
whatever did not fit behind a small overflow arrow, and on a laptop screen
half of the editor's buttons were simply gone. Here a row first drops the
labels of its buttons and keeps the icons; if even that does not fit, it
wraps onto a second line. Nothing is hidden at any window size.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QWidget,
)

from . import icons, theme

# Breathing room when deciding whether the labels fit, so a row that is
# exactly at the edge does not flip between the two looks while resizing.
SLACK = 12


class FlowLayout(QLayout):
    """Lays its items out in a row and wraps them onto new lines as needed.

    Right to left like the window it sits in. A stretch (`addStretch`) takes
    whatever room is left on its line, which is how a group of buttons is
    pushed to the far end -- and when the line wraps, the stretch simply
    collapses instead of leaving a hole.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = theme.SPACE * 2,
                 line_spacing: int | None = None) -> None:
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._line_spacing = spacing if line_spacing is None else line_spacing
        self.setContentsMargins(0, 0, 0, 0)

    # QLayout plumbing
    def addItem(self, item) -> None:  # noqa: N802 - Qt naming
        self._items.append(item)

    def addStretch(self) -> None:  # noqa: N802 - Qt naming
        self.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt naming
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt naming
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt naming
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt naming
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        """Everything on one line: what the row would like to have."""
        width = height = 0
        visible = [i for i in self._visible() if not isinstance(i, QSpacerItem)]
        for item in visible:
            hint = item.sizeHint()
            width += hint.width()
            height = max(height, hint.height())
        width += self._spacing * max(0, len(visible) - 1)
        margins = self.contentsMargins()
        return QSize(width + margins.left() + margins.right(),
                     height + margins.top() + margins.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt naming
        """As narrow as the widest item; as tall as the lines it wraps into.

        The height is the one thing a plain flow layout gets wrong: asked for
        its minimum it reports a single line, and a short window then squeezed
        the wrapped lines on top of each other. Reporting the height the
        current width really needs makes the window give the room up from
        the stretchy parts instead.
        """
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        width = self.geometry().width()
        if width > 0:
            size.setHeight(max(size.height(), self.heightForWidth(width)))
        return size

    def one_line_width(self) -> int:
        return self.sizeHint().width()

    # layout
    def _visible(self):
        return [item for item in self._items if isinstance(item, QSpacerItem) or not item.isEmpty()]

    def _arrange(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        limit = max(1, area.width())

        # First pass: break the items into lines.
        lines: list[list] = [[]]
        used = 0
        for item in self._visible():
            if isinstance(item, QSpacerItem):
                lines[-1].append(item)
                continue
            width = min(item.sizeHint().width(), limit)
            gap = self._spacing if any(not isinstance(i, QSpacerItem) for i in lines[-1]) else 0
            if used and used + gap + width > limit:
                lines.append([])
                used = 0
                gap = 0
            lines[-1].append(item)
            used += gap + width

        # Second pass: place them, each line centred on its own tallest item.
        rtl = self.parentWidget() is not None and self.parentWidget().layoutDirection() == Qt.RightToLeft
        y = area.y()
        for line in lines:
            solid = [i for i in line if not isinstance(i, QSpacerItem)]
            if not solid:
                continue
            widths = [min(i.sizeHint().width(), limit) for i in solid]
            height = max(i.sizeHint().height() for i in solid)
            spare = limit - sum(widths) - self._spacing * (len(solid) - 1)
            stretches = sum(1 for i in line if isinstance(i, QSpacerItem))
            x = 0
            for item in line:
                if isinstance(item, QSpacerItem):
                    x += max(0, spare) // stretches if stretches else 0
                    continue
                width = min(item.sizeHint().width(), limit)
                item_height = item.sizeHint().height()
                if item.expandingDirections() & Qt.Vertical:
                    item_height = height
                if apply:
                    left = area.x() + (limit - x - width if rtl else x)
                    top = y + (height - item_height) // 2
                    item.setGeometry(QRect(left, top, width, item_height))
                x += width + self._spacing
            y += height + self._line_spacing
        y -= self._line_spacing if any(lines) else 0
        return max(0, y - rect.y()) + margins.bottom()


class ActionButton(QToolButton):
    """An icon with a label, which can give up its label when room runs out.

    The label then moves into the tooltip, so hovering still says what the
    button does.
    """

    def __init__(self, text: str, icon: str | None = None, *, name: str = "",
                 collapsible: bool = True, icon_only: bool = False, priority: int = 2,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if name:
            self.setObjectName(name)
        self.icon_name = icon
        # Lower gives up its label first when the row runs short of room.
        self.priority = priority
        self.collapsible = collapsible and icon is not None
        self.icon_only = icon_only and icon is not None
        self.compact = False
        self._tip = ""
        self._icon_painted = False
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(theme.ICON, theme.ICON))
        self.setFocusPolicy(Qt.TabFocus)
        super().setText(text)
        self.setAccessibleName(text)
        self._apply_style()

    # label and tooltip
    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        super().setText(text)
        self.setAccessibleName(text)
        self._sync_tip()
        self.updateGeometry()

    def setToolTip(self, tip: str) -> None:  # noqa: N802 - Qt naming
        self._tip = tip
        self._sync_tip()

    def _sync_tip(self) -> None:
        hidden_label = self.icon_only or self.compact
        if hidden_label and self._tip:
            super().setToolTip(f"{self.text()}\n{self._tip}")
        else:
            super().setToolTip(self._tip or (self.text() if hidden_label else ""))

    # look
    def set_compact(self, compact: bool) -> None:
        compact = compact and self.collapsible
        if compact == self.compact:
            return
        self.compact = compact
        self._apply_style()

    def _apply_style(self) -> None:
        bare = self.icon_only or self.compact
        if self.icon_name is None:
            self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        else:
            self.setToolButtonStyle(Qt.ToolButtonIconOnly if bare else Qt.ToolButtonTextBesideIcon)
        self.setProperty("compact", "true" if bare else "false")
        # A dynamic property only takes effect once the style looks again.
        self.style().unpolish(self)
        self.style().polish(self)
        self._sync_tip()
        self.updateGeometry()

    # measuring and painting
    #
    # Qt's own tool button put the icon on the wrong side in a right-to-left
    # window, and left a gap beside it; the content is drawn here instead:
    # icon at the start of the reading direction, label after it, the pair
    # centred in the button.
    GAP = 6

    def _height(self) -> int:
        role = self.objectName()
        if role == "Round":
            return theme.CONTROL_HEIGHT + 6
        if role.startswith("Chip"):
            return theme.CONTROL_HEIGHT - 8
        if isinstance(self.parentWidget(), Segment):
            return theme.CONTROL_HEIGHT - 6
        return theme.CONTROL_HEIGHT

    def _padding(self) -> int:
        role = self.objectName()
        if role == "Primary":
            return theme.SPACE * 5
        return theme.SPACE * 3

    def _shows_label(self) -> bool:
        return bool(self.text()) and (self.icon_name is None or not (self.icon_only or self.compact))

    def _measure(self, labelled: bool) -> QSize:
        height = self._height()
        has_icon = self.icon_name is not None
        if has_icon and not labelled:
            return QSize(height, height)
        icon = self.iconSize().width() if has_icon else 0
        text = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        gap = self.GAP if icon and text else 0
        return QSize(icon + gap + text + 2 * self._padding() + 2, height)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self._measure(self._shows_label())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.sizeHint()

    def full_width(self) -> int:
        """How wide the button is with its label, whatever it shows now."""
        return self._measure(True).width()

    def _ink(self) -> QColor:
        tokens = theme.tokens_for(self)
        role = self.objectName()
        if not self.isEnabled():
            return QColor(tokens.border_strong if role in ("Quiet", "Danger") else tokens.text_muted)
        if self.isChecked():
            return QColor(tokens.accent)
        if role == "Quiet" and self.underMouse():
            return QColor(tokens.text)
        return QColor({
            "Primary": tokens.accent_text,
            "Round": tokens.accent_text,
            "Danger": tokens.danger,
            "Quiet": tokens.text_muted,
            "ChipWarn": tokens.warn,
            "ChipOk": tokens.ok,
            "Chip": tokens.text_muted,
        }.get(role, tokens.text))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QStylePainter

        painter = QStylePainter(self)
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        # The frame, hover and pressed looks still come from the style sheet.
        option.text = ""
        option.icon = QIcon()
        painter.drawComplexControl(QStyle.CC_ToolButton, option)

        label = self._shows_label()
        icon_size = self.iconSize() if self.icon_name is not None else QSize(0, 0)
        text_width = self.fontMetrics().horizontalAdvance(self.text()) if label else 0
        gap = self.GAP if icon_size.width() and text_width else 0
        total = icon_size.width() + gap + text_width
        left = (self.width() - total) / 2
        rtl = self.layoutDirection() == Qt.RightToLeft
        icon_x = left + total - icon_size.width() if rtl else left
        text_x = left if rtl else left + icon_size.width() + gap
        if self.isDown() and self.objectName() not in ("Round",):
            icon_x += 0.5

        if icon_size.width():
            mode = QIcon.Normal if self.isEnabled() else QIcon.Disabled
            pixmap = self.icon().pixmap(icon_size, self.devicePixelRatioF(), mode)
            painter.drawPixmap(int(round(icon_x)), (self.height() - icon_size.height()) // 2, pixmap)
        if label:
            painter.setPen(self._ink())
            painter.setFont(self.font())
            painter.drawText(
                QRectF(text_x, 0, text_width + 2, self.height()),
                Qt.AlignVCenter | Qt.AlignHCenter,
                self.text(),
            )
        painter.end()

    # icon
    def set_icon(self, name: str | None) -> None:
        self.icon_name = name
        if self._icon_painted or self.isVisible():
            self.repaint_icon()

    def repaint_icon(self) -> None:
        """Draw the icon in the colour the button's text has right now."""
        self._icon_painted = True
        if self.icon_name is None:
            return
        tokens = theme.tokens_for(self)
        role = self.objectName()
        colour = {
            "Primary": tokens.accent_text,
            "Round": tokens.accent_text,
            "Danger": tokens.danger,
            "Quiet": tokens.text_muted,
            "ChipWarn": tokens.warn,
            "ChipOk": tokens.ok,
            "Chip": tokens.text_muted,
        }.get(role, tokens.text)
        disabled = tokens.border_strong if role in ("Quiet", "Danger") else tokens.text_muted
        self.setIcon(icons.make(self.icon_name, colour, disabled, self.iconSize().width()))

    def set_role(self, role: str) -> None:
        """Switch to another look (a chip turning from warning to ok, say)."""
        if role == self.objectName():
            return
        self.setObjectName(role)
        self.style().unpolish(self)
        self.style().polish(self)
        self.repaint_icon()
        self.updateGeometry()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._icon_painted:
            self.repaint_icon()
        super().showEvent(event)


class Segment(QFrame):
    """A few related commands in one rounded frame."""

    def __init__(self, *buttons: QWidget) -> None:
        super().__init__()
        self.setObjectName("Segment")
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        for button in buttons:
            row.addWidget(button)
        self.buttons = list(buttons)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class ResponsiveRow(QWidget):
    """A wrapping row that drops button labels before it has to wrap.

    Every collapsible ActionButton anywhere inside it -- directly or in a
    Segment -- turns icon-only together when the labelled row would not fit
    the width the row has been given.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = theme.SPACE * 2) -> None:
        super().__init__(parent)
        self.setObjectName("Bare")
        self.flow = FlowLayout(self, spacing=spacing)
        self.compact = False
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def add(self, widget: QWidget) -> QWidget:
        self.flow.addWidget(widget)
        return widget

    def add_stretch(self) -> None:
        self.flow.addStretch()

    def _buttons(self) -> list[ActionButton]:
        return [b for b in self.findChildren(ActionButton) if b.collapsible and b.isVisibleTo(self)]

    def width_at(self, level: int) -> int:
        """One line's width with every label up to `level` dropped."""
        width = self.flow.one_line_width()
        for button in self._buttons():
            now = button.sizeHint().width()
            wanted = button._measure(button.priority > level).width()
            width += wanted - now
        return width

    def fit(self, width: int | None = None) -> None:
        """Drop labels a priority at a time, the least important first.

        A single all-or-nothing switch turned the whole bar into a row of
        bare icons the moment one label did not fit; now the long, rarely
        used ones go first and the main commands keep their words longest.
        """
        width = self.width() if width is None else width
        buttons = self._buttons()
        levels = sorted({b.priority for b in buttons})
        chosen = levels[-1] if levels else 0
        for level in [min(levels, default=0) - 1] + levels:
            if self.width_at(level) <= width - SLACK:
                chosen = level
                break
        changed = False
        for button in buttons:
            compact = button.priority <= chosen
            if compact != button.compact:
                button.set_compact(compact)
                changed = True
        self.compact = any(b.compact for b in buttons)
        if changed:
            self.flow.invalidate()
            self.updateGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.fit(event.size().width())
        super().resizeEvent(event)


class ToggleSwitch(QCheckBox):
    """An on/off switch with its label: a checkbox that reads as a setting.

    Still a QCheckBox underneath, so everything that calls `isChecked`,
    `setChecked` or listens to `toggled` keeps working unchanged.
    """

    TRACK_W = 34
    TRACK_H = 20
    GAP = 8

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._offset = 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(theme.MOTION_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, on: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if on else 0.0)
        self._animation.start()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        text = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        width = self.TRACK_W + (self.GAP + text if text else 0) + 4
        return QSize(width, max(theme.CONTROL_HEIGHT - 4, self.TRACK_H + 4))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802 - Qt naming
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._animation.state() != QPropertyAnimation.Running:
            # Set from code, with signals blocked or before the window
            # showed: there was no animation, so the knob catches up here.
            self._offset = 1.0 if self.isChecked() else 0.0
        tokens = theme.tokens_for(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rtl = self.layoutDirection() == Qt.RightToLeft
        top = (self.height() - self.TRACK_H) / 2
        left = self.width() - self.TRACK_W - 2 if rtl else 2
        track = QRectF(left, top, self.TRACK_W, self.TRACK_H)

        off = QColor(tokens.border_strong)
        on = QColor(tokens.accent)
        t = self._offset
        mixed = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        if not self.isEnabled():
            mixed.setAlpha(110)
        painter.setPen(Qt.NoPen)
        painter.setBrush(mixed)
        painter.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)

        knob = self.TRACK_H - 6
        travel = self.TRACK_W - knob - 6
        # "On" is the reading direction's far end: left in Persian.
        position = (1 - t) if rtl else t
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(track.left() + 3 + travel * position, top + 3, knob, knob))

        if self.hasFocus():
            ring = QColor(tokens.focus_ring)
            ring.setAlpha(120)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(ring)
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), self.TRACK_H / 2 + 2, self.TRACK_H / 2 + 2)

        if self.text():
            painter.setPen(QColor(tokens.text if self.isEnabled() else tokens.text_muted))
            text_rect = (
                QRectF(0, 0, track.left() - self.GAP, self.height())
                if rtl
                else QRectF(track.right() + self.GAP, 0, self.width() - track.right() - self.GAP, self.height())
            )
            painter.drawText(text_rect, Qt.AlignVCenter | (Qt.AlignRight if rtl else Qt.AlignLeft), self.text())
        painter.end()


def refresh_icons(root: QWidget) -> None:
    """Redraw every icon under `root` -- after a theme switch, say."""
    for button in root.findChildren(ActionButton):
        button.repaint_icon()
