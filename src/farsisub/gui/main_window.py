"""Main window: drop videos, watch them turn into subtitles.

Layout is right-to-left throughout, except for timecodes and file paths which
stay left-to-right because that is how they are actually read.
"""

from __future__ import annotations

import copy
import logging
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTime, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import BUILTIN_PROFILES, AppConfig
from ..engine import locate, modelstore
from . import theme
from .editor import EditorDialog
from ..text.normalize import to_persian_digits
from .worker import Job, TranscribeWorker

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
MEDIA_SUFFIXES = VIDEO_SUFFIXES | AUDIO_SUFFIXES

# One filter line, so the file dialog opens showing everything that works.
MEDIA_FILTER = (
    "ویدیو و صدا (" + " ".join(f"*{s}" for s in sorted(MEDIA_SUFFIXES)) + ");;"
    "ویدیو (" + " ".join(f"*{s}" for s in sorted(VIDEO_SUFFIXES)) + ");;"
    "صدا (" + " ".join(f"*{s}" for s in sorted(AUDIO_SUFFIXES)) + ");;"
    "همه فایل‌ها (*)"
)


def media_paths(urls) -> list[Path]:
    """The files in a drop that this program can actually read."""
    paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
    return [p for p in paths if p.suffix.lower() in MEDIA_SUFFIXES]

STATUS_QUEUED = "در صف"
STATUS_RUNNING = "در حال پردازش"
STATUS_DONE = "آماده"
STATUS_FAILED = "خطا"
STATUS_CANCELLED = "لغو شد"

# What the start button picks up: a file that failed or was stopped is worth
# another try when the user asks for one.
STARTABLE = (STATUS_QUEUED, STATUS_FAILED, STATUS_CANCELLED)


class AppMark(QWidget):
    """The product mark: a rounded tile with a subtitle glyph inside.

    Drawn rather than shipped as an asset, so it scales with the window and
    needs no icon file in the bundle.
    """

    def __init__(self, size: int = 40) -> None:
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        from PySide6.QtGui import QColor, QPainter, QPainterPath

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = self.rect().adjusted(0, 0, -1, -1)

        tile = QPainterPath()
        tile.addRoundedRect(box, theme.RADIUS, theme.RADIUS)
        painter.fillPath(tile, QColor(theme.DARK.accent))

        # Two subtitle lines, the shorter one centred underneath.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.DARK.accent_text))
        unit = self._size / 10
        painter.drawRoundedRect(
            QRectF(unit * 2, unit * 5.4, unit * 6, unit * 0.9), unit * 0.45, unit * 0.45
        )
        painter.drawRoundedRect(
            QRectF(unit * 3.2, unit * 7.1, unit * 3.6, unit * 0.9), unit * 0.45, unit * 0.45
        )
        painter.end()


class DropGlyph(QWidget):
    """An arrow into a tray: the one picture the empty state needs."""

    def __init__(self, size: int = 64) -> None:
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        from PySide6.QtGui import QColor, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        unit = self._size / 16
        pen = QPen(QColor(theme.DARK.text_muted))
        pen.setWidthF(unit * 0.9)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        # Downward arrow.
        painter.drawLine(QPointF(unit * 8, unit * 2), QPointF(unit * 8, unit * 9))
        painter.drawLine(QPointF(unit * 5, unit * 6), QPointF(unit * 8, unit * 9))
        painter.drawLine(QPointF(unit * 11, unit * 6), QPointF(unit * 8, unit * 9))
        # The tray it lands in.
        painter.drawLine(QPointF(unit * 3, unit * 11), QPointF(unit * 3, unit * 13.5))
        painter.drawLine(QPointF(unit * 3, unit * 13.5), QPointF(unit * 13, unit * 13.5))
        painter.drawLine(QPointF(unit * 13, unit * 13.5), QPointF(unit * 13, unit * 11))
        painter.end()


class DropZone(QFrame):
    """The empty state: never a blank window."""

    def __init__(self, on_files) -> None:
        super().__init__()
        self.setObjectName("DropZoneIdle")
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self._on_files = on_files

        # One centred group, not a title at the top and a hint stranded at
        # the bottom of an empty rectangle.
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE * 2)
        layout.addStretch(1)

        glyph = DropGlyph()
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(glyph)
        holder.addStretch(1)
        layout.addLayout(holder)

        title = QLabel("ویدیو یا فایل صوتی را اینجا رها کن")
        title.setObjectName("Heading")
        title.setAlignment(Qt.AlignCenter)
        hint = QLabel("هر جای پنجره هم رها کنی می‌گیرد — یا از سیستم انتخاب کن")
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(hint)

        pick = QPushButton("انتخاب فایل")
        pick.setObjectName("Primary")
        pick.clicked.connect(self.choose_files)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(pick)
        buttons.addStretch(1)
        layout.addSpacing(theme.SPACE)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.choose_files()

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "انتخاب ویدیو یا صدا", "", MEDIA_FILTER)
        if paths:
            self._on_files([Path(p) for p in paths])

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        log.info("درگ روی ناحیه رها کردن: %s", event.mimeData().formats())
        if event.mimeData().hasUrls():
            self.setObjectName("DropZoneActive")
            self.setStyleSheet(self.styleSheet())  # force a repaint of the border
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        # Accepting the enter is not enough: every move has to be answered as
        # well, or the cursor keeps saying "no" and the drop never arrives.
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setObjectName("DropZoneIdle")
        self.setStyleSheet(self.styleSheet())

    def dropEvent(self, event) -> None:  # noqa: N802
        self.setObjectName("DropZoneIdle")
        self.setStyleSheet(self.styleSheet())
        urls = event.mimeData().urls()
        wanted = media_paths(urls)
        log.info("رها شد روی ناحیه: %d آدرس، %d قابل استفاده", len(urls), len(wanted))
        if wanted:
            self._on_files(wanted)
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config = config or AppConfig()
        self.queue: list[Path] = []
        # The Job holds worker + thread together. Dropping a QThread reference
        # while it still runs kills the process, so nothing is released until
        # the thread reports finished.
        self.job: Job | None = None
        self.started_at = 0.0
        self.last_output: Path | None = None
        # Kept so the editor can reopen the last result without re-running.
        self.last_project = None
        self.running_path: Path | None = None
        # Set by cancel: the queue stops after the current file instead of
        # moving on to the next one.
        self.stop_requested = False

        self.setWindowTitle("FarsiSub — زیرنویس فارسی")
        self.setLayoutDirection(Qt.RightToLeft)
        # Dropping onto the queue, the options or anywhere else used to do
        # nothing at all: only the dashed strip listened.
        self.setAcceptDrops(True)
        self.resize(980, 640)
        self._build()
        self._refresh_model_state()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(theme.SPACE * 4, theme.SPACE * 4, theme.SPACE * 4, theme.SPACE * 4)
        layout.setSpacing(theme.SPACE * 3)

        layout.addWidget(self._header())
        layout.addWidget(self._options())
        layout.addWidget(self._work_surface(), stretch=1)
        layout.addWidget(self._footer())

        self.setCentralWidget(root)
        self._shortcuts()

    def _header(self) -> QWidget:
        """Name, one line of promise, and the engine state as a chip.

        The old header was a single bold sentence in a corner: nothing said
        which program this was, and the engine state read as an afterthought.
        """
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, theme.SPACE)
        row.setSpacing(theme.SPACE * 3)

        row.addWidget(AppMark())

        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel("FarsiSub")
        title.setObjectName("Display")
        subtitle = QLabel("فارسی‌ساب — زیرنویس فارسی، کاملاً روی همین کامپیوتر")
        subtitle.setObjectName("Muted")
        names.addWidget(title)
        names.addWidget(subtitle)
        row.addLayout(names)

        row.addStretch(1)
        self.engine_label = QLabel()
        self.engine_label.setObjectName("Chip")
        row.addWidget(self.engine_label)
        return box

    def _options(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        row = QHBoxLayout(card)
        row.setContentsMargins(theme.SPACE * 3, theme.SPACE * 3, theme.SPACE * 3, theme.SPACE * 3)
        row.setSpacing(theme.SPACE * 3)

        self.profile_box = QComboBox()
        for name, profile in BUILTIN_PROFILES.items():
            self.profile_box.addItem(profile.label, name)
        self.profile_box.setCurrentIndex(
            self.profile_box.findData(self.config.profile.name)
        )
        self.profile_box.currentIndexChanged.connect(self._profile_changed)

        self.model_box = QComboBox()
        self.model_box.currentIndexChanged.connect(self._model_changed)

        # Two models, second one only for the gaps. Costs a second pass.
        self.merge_box = QCheckBox("ترکیب دو مدل")
        self.merge_box.setToolTip(
            "مدل دوم فقط جاهایی را می‌نویسد که مدل اول ساکت مانده. "
            "دقیق‌تر است ولی زمان پردازش دو برابر می‌شود."
        )
        self.merge_box.toggled.connect(self._merge_toggled)

        self.digits_box = QCheckBox("ارقام فارسی")
        self.digits_box.setChecked(self.config.text.persian_digits)
        self.digits_box.toggled.connect(
            lambda on: setattr(self.config.text, "persian_digits", on)
        )

        self.period_box = QCheckBox("نقطه انتهای جمله")
        self.period_box.setChecked(not self.config.text.strip_final_period)
        self.period_box.toggled.connect(
            lambda on: setattr(self.config.text, "strip_final_period", not on)
        )

        def field(caption: str, widget) -> QVBoxLayout:
            """A control with its label above it, not floating beside it."""
            column = QVBoxLayout()
            column.setSpacing(theme.SPACE)
            label = QLabel(caption)
            label.setObjectName("Caption")
            column.addWidget(label)
            column.addWidget(widget)
            return column

        row.addLayout(field("سبک زیرنویس", self.profile_box))
        row.addLayout(field("مدل", self.model_box))

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setObjectName("Divider")
        line.setFixedWidth(1)
        row.addWidget(line)

        switches = QVBoxLayout()
        switches.setSpacing(theme.SPACE)
        caption = QLabel("گزینه‌ها")
        caption.setObjectName("Caption")
        switches.addWidget(caption)
        boxes = QHBoxLayout()
        boxes.setSpacing(theme.SPACE * 4)
        boxes.addWidget(self.merge_box)
        boxes.addWidget(self.digits_box)
        boxes.addWidget(self.period_box)
        switches.addLayout(boxes)
        row.addLayout(switches)

        row.addStretch(1)
        return card

    def _work_surface(self) -> QWidget:
        """One card that is either the invitation or the queue -- never both.

        The window used to show a dashed strip at the top and, underneath, a
        large empty table with nothing to say. Now the empty state lives
        inside the card and the queue replaces it once there is work.
        """
        card = QFrame()
        card.setObjectName("Card")
        theme.elevate(card)
        column = QVBoxLayout(card)
        column.setContentsMargins(theme.SPACE * 3, theme.SPACE * 3, theme.SPACE * 3, theme.SPACE * 3)
        column.setSpacing(theme.SPACE * 2)

        self.stack = QStackedWidget()
        self.drop_zone = DropZone(self.add_files)
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self._table())
        column.addWidget(self.stack, stretch=1)
        return card

    def _show_queue(self) -> None:
        """Swap the invitation for the list, or back when the queue empties."""
        self.stack.setCurrentIndex(1 if self.table.rowCount() else 0)

    def _table(self) -> QWidget:
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["فایل", "وضعیت", "خروجی"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.itemDoubleClicked.connect(self._row_double_clicked)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        return self.table

    def _footer(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE * 2)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        # The bar fills left-to-right; only the label inside it is Persian.
        self.progress.setLayoutDirection(Qt.LeftToRight)

        self.status_label = QLabel("آماده")
        self.status_label.setObjectName("Muted")

        self.start_button = QPushButton("شروع رونویسی")
        self.start_button.setObjectName("Primary")
        self.start_button.clicked.connect(self.start_queue)

        self.cancel_button = QPushButton("لغو")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)

        self.edit_button = QPushButton("ویرایش زیرنویس")
        self.edit_button.setEnabled(False)
        self.edit_button.setToolTip("اصلاح کلمات و جابه‌جایی خط‌ها، بدون خراب شدن زمان‌ها")
        self.edit_button.clicked.connect(self.open_editor)

        self.open_button = QPushButton("باز کردن پوشه")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_output_folder)

        # Running the same file again with another model or style is the normal
        # way to work, not an edge case.
        self.again_button = QPushButton("پردازش دوباره")
        self.again_button.setEnabled(False)
        self.again_button.clicked.connect(self.requeue)

        self.clear_button = QPushButton("پاک کردن صف")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self.clear_queue)

        # Seven buttons of equal weight told the eye nothing. The one action
        # that matters keeps its colour; the rest go quiet, and the progress
        # bar is a hairline over them instead of an empty pill.
        for quiet in (self.clear_button, self.again_button, self.open_button):
            quiet.setObjectName("Quiet")

        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACE * 2)
        column.addWidget(self.progress)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE * 2)
        row.addWidget(self.status_label)
        row.addStretch(1)
        row.addWidget(self.clear_button)
        row.addWidget(self.again_button)
        row.addWidget(self.open_button)
        row.addWidget(self.edit_button)
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
        column.addLayout(row)
        return box

    def _shortcuts(self) -> None:
        add = QAction("افزودن فایل", self)
        add.setShortcut(QKeySequence.Open)
        add.triggered.connect(lambda: self._pick_files())
        self.addAction(add)

        run = QAction("شروع", self)
        run.setShortcut(QKeySequence("Ctrl+Return"))
        run.triggered.connect(self.start_queue)
        self.addAction(run)

        again = QAction("پردازش دوباره", self)
        again.setShortcut(QKeySequence("Ctrl+R"))
        again.triggered.connect(self.requeue)
        self.addAction(again)

        remove = QAction("حذف از صف", self)
        remove.setShortcut(QKeySequence.Delete)
        remove.triggered.connect(self.remove_selected)
        self.addAction(remove)

        clear = QAction("پاک کردن صف", self)
        clear.setShortcut(QKeySequence("Ctrl+Shift+X"))
        clear.triggered.connect(self.clear_queue)
        self.addAction(clear)

    # ------------------------------------------------------------- behaviour

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "انتخاب ویدیو یا صدا", "", MEDIA_FILTER)
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        for path in paths:
            if path in self.queue:
                continue
            self.queue.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)
            # A Latin name inside a right-to-left table gets reordered by the
            # bidi algorithm -- "5.wav" came out as "wav.5". The isolate marks
            # pin it down.
            name_item = QTableWidgetItem(f"\u2066{path.name}\u2069")  # LRI ... PDI
            # File names are usually Latin: pin them to the visual left even
            # though the window itself is right-to-left.
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
            name_item.setToolTip(str(path))
            self.table.setItem(row, 0, name_item)
            self._show_queue()
            status_item = QTableWidgetItem(STATUS_QUEUED)
            self.table.setItem(row, 1, status_item)
            self._paint_status(status_item)
            self.table.setItem(row, 2, QTableWidgetItem(""))
        self._update_buttons()

    def requeue(self) -> None:
        """Put finished files back in the queue: same video, new settings."""
        if self.job is not None:
            return
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            rows = set(range(self.table.rowCount()))
        for row in rows:
            self.table.item(row, 1).setText(STATUS_QUEUED)
            self._paint_status(self.table.item(row, 1))
            self.table.item(row, 2).setText("")
        self.progress.setValue(0)
        self.status_label.setText("آماده")
        self._update_buttons()

    def remove_selected(self) -> None:
        if self.job is not None:
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.queue[row]
        self._show_queue()  # emptying the list by hand also brings it back
        self._update_buttons()

    def clear_queue(self) -> None:
        if self.job is not None:
            return
        self.table.setRowCount(0)
        self.queue.clear()
        self.last_output = None
        self.open_button.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText("آماده")
        self._show_queue()  # an empty queue means the invitation comes back
        self._update_buttons()

    def _profile_changed(self, index: int) -> None:
        name = self.profile_box.itemData(index)
        if name:
            self.config.profile = BUILTIN_PROFILES[name]

    def _model_changed(self, index: int) -> None:
        name = self.model_box.itemData(index)
        if name:
            self.config.model_name = name
        self._merge_toggled(self.merge_box.isChecked())

    def _merge_toggled(self, enabled: bool) -> None:
        """Pick the other installed model as the gap filler."""
        others = [m for m in locate.installed_models() if m != self.config.model_name]
        if enabled and others:
            self.config.merge_model = others[0]
            self.merge_box.setText(f"ترکیب با {others[0]}")
        else:
            self.config.merge_model = None
            self.merge_box.setText("ترکیب دو مدل")
        self.merge_box.setEnabled(bool(others))

    def _refresh_model_state(self) -> None:
        installed = locate.installed_models()
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for info in modelstore.CATALOG:
            if info.name in installed:
                self.model_box.addItem(info.label, info.name)
        for name in locate.custom_models():
            self.model_box.addItem(f"{name} (اختصاصی)", name)
        self.model_box.blockSignals(False)

        if installed:
            index = self.model_box.findData(self.config.model_name)
            if index < 0:
                index = 0
                self.config.model_name = self.model_box.itemData(0)
            self.model_box.setCurrentIndex(index)
        else:
            self.model_box.addItem("هیچ مدلی نصب نیست", None)

        self._merge_toggled(self.merge_box.isChecked())
        binary = locate.whisper_binary()
        # Naming the models beats counting them: the dropdown only shows the
        # selected one until it is opened.
        # A chip, not a sentence: state first, then how many models back it.
        if binary and installed:
            self.engine_label.setObjectName("ChipOk")
            count = to_persian_digits(str(len(installed)))
            self.engine_label.setText(f"موتور آماده · {count} مدل")
        else:
            self.engine_label.setObjectName("Chip")
            self.engine_label.setText("موتور آماده نیست" if not binary else "مدلی نصب نیست")
        self.engine_label.setToolTip(
            "مدل‌های نصب‌شده: " + ("، ".join(installed) if installed else "هیچ‌کدام")
        )
        self.engine_label.setStyleSheet(self.engine_label.styleSheet())  # re-apply
        self._update_buttons()

    def _update_buttons(self) -> None:
        idle = self.job is None
        pending = any(
            self.table.item(row, 1).text() in STARTABLE
            for row in range(self.table.rowCount())
        )
        self.start_button.setEnabled(idle and pending and bool(locate.installed_models()))
        self.cancel_button.setEnabled(not idle)
        self.again_button.setEnabled(idle and bool(self.queue) and not pending)
        self.clear_button.setEnabled(idle and bool(self.queue))
        has_project = self.last_project is not None or any(
            locate.project_path(p).exists() for p in self.queue
        )
        self.edit_button.setEnabled(idle and has_project)

    def _row_for(self, path: Path) -> int:
        return self.queue.index(path)

    STATUS_COLOURS = {
        STATUS_RUNNING: "accent",
        STATUS_DONE: "ok",
        STATUS_FAILED: "danger",
    }

    def _paint_status(self, item) -> None:
        """Colour carries the state, so the column can be read at a glance."""
        from PySide6.QtGui import QBrush, QColor

        token = self.STATUS_COLOURS.get(item.text(), "text_muted")
        item.setForeground(QBrush(QColor(getattr(theme.DARK, token))))

    def _set_status(self, path: Path, status: str, output: str = "") -> None:
        row = self._row_for(path)
        item = self.table.item(row, 1)
        item.setText(status)
        self._paint_status(item)
        if output:
            self.table.item(row, 2).setText(output)

    # ---------------------------------------------------------------- queue

    def _pending(self, statuses: tuple[str, ...]) -> list[Path]:
        return [
            path
            for i, path in enumerate(self.queue)
            if self.table.item(i, 1).text() in statuses
        ]

    def start_queue(self) -> None:
        """The start button: everything waiting, plus what failed or was stopped."""
        if self.job is not None:
            return
        self.stop_requested = False
        pending = self._pending(STARTABLE)
        if pending:
            self._run(pending[0])

    def _continue_queue(self) -> None:
        """After a file ends: only files still waiting, never a retry.

        Picking failed files up here too meant a cancelled file started over
        straight away, and a file that always fails (no audio track, a broken
        container) ran again and again, an error box each time.
        """
        if self.stop_requested:
            self.stop_requested = False
            return
        if self.job is not None:
            return
        pending = self._pending((STATUS_QUEUED,))
        if pending:
            self._run(pending[0])

    def _run(self, path: Path) -> None:
        self.started_at = time.time()
        self._set_status(path, STATUS_RUNNING)
        self.progress.setValue(0)
        self.status_label.setText(f"در حال پردازش {path.name}")

        # Which file this job is for; the slots below run later, on the GUI
        # thread, and need it.
        self.running_path = path

        # A copy: the worker reads the settings on its own thread for minutes,
        # and a switch flipped meanwhile must not land halfway through a file.
        worker = TranscribeWorker(path, copy.deepcopy(self.config))
        # Bound methods with `self` as receiver, and QueuedConnection spelled
        # out. A lambda here has no receiver object, so Qt runs it on the
        # WORKER thread -- and touching a widget from there crashes the process
        # with an access violation. That is exactly what happened.
        worker.progress.connect(self._on_progress, Qt.QueuedConnection)
        worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        worker.failed.connect(self._on_failed, Qt.QueuedConnection)
        worker.stopped.connect(self._on_cancelled, Qt.QueuedConnection)

        job = Job(worker)
        # Clean-up and the next queue item wait for the THREAD, not the worker.
        job.thread.finished.connect(self._job_finished, Qt.QueuedConnection)
        self.job = job
        job.start()
        self._update_buttons()

    def _on_progress(self, percent: int) -> None:
        self.progress.setValue(percent)
        if percent > 2:
            elapsed = time.time() - self.started_at
            remaining = elapsed * (100 - percent) / percent
            self.status_label.setText(
                "باقی‌مانده حدود " + QTime(0, 0).addSecs(int(remaining)).toString("mm:ss")
            )

    def _on_finished(self, project, output) -> None:
        """Runs on the GUI thread, after the worker signals success."""
        path = self.running_path
        output = Path(output)
        if path is not None:
            self._set_status(path, STATUS_DONE, output.name)
        self.last_output = output
        self.last_project = project
        self.open_button.setEnabled(True)
        self.edit_button.setEnabled(True)
        self.status_label.setText("انجام شد")
        self.progress.setValue(100)

    def _on_failed(self, message: str) -> None:
        path = self.running_path
        if path is not None:
            self._set_status(path, STATUS_FAILED)
        self.status_label.setText("خطا")
        QMessageBox.warning(self, "پردازش انجام نشد", message)

    def _on_cancelled(self) -> None:
        path = self.running_path
        if path is not None:
            self._set_status(path, STATUS_CANCELLED)
        self.progress.setValue(0)
        self.status_label.setText("لغو شد")

    def _job_finished(self) -> None:
        # `finished` fires as the thread is winding down, not once it is gone.
        # Dropping the reference here let the next queue item replace the Job
        # while the old QThread was still alive: "QThread: Destroyed while
        # thread is still running", which takes the process with it.
        job, self.job = self.job, None
        if job is not None:
            job.thread.wait(10_000)
        self._update_buttons()
        self._continue_queue()

    def cancel(self) -> None:
        if self.job is not None:
            self.stop_requested = True
            self.job.worker.cancel()
            self.status_label.setText("در حال لغو…")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Never let the window die while a worker thread is still alive."""
        if self.job is not None:
            self.stop_requested = True
            if self.job.stop():
                self.job = None
            # Otherwise the reference is kept: dropping a QThread that is
            # still running takes the process down with it.
        super().closeEvent(event)

    def refresh_models(self) -> None:
        """Public: re-read the models folder (a model may have just arrived)."""
        self._refresh_model_state()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        log.info("درگ روی پنجره: %s", event.mimeData().formats())
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        urls = event.mimeData().urls()
        wanted = media_paths(urls)
        log.info("رها شد روی پنجره: %d آدرس، %d قابل استفاده", len(urls), len(wanted))
        if wanted:
            self.add_files(wanted)
            event.acceptProposedAction()
        elif urls:
            QMessageBox.information(
                self,
                "این فایل خوانده نمی‌شود",
                "فقط ویدیو و فایل صوتی: "
                + "، ".join(sorted(s.lstrip(".") for s in MEDIA_SUFFIXES)),
            )

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            # Cheap directory listing; keeps a long-lived window honest about
            # models installed after it opened.
            self._refresh_model_state()
        super().changeEvent(event)

    def _row_double_clicked(self, item) -> None:
        self.open_editor(row=item.row())

    def _project_for(self, path: Path):
        """The saved WordStream for a file, from this session or from disk."""
        from ..models import Project

        if self.last_project is not None and Path(self.last_project.video_path) == path:
            return self.last_project
        saved = locate.project_path(path)
        if saved.exists():
            try:
                return Project.load(saved)
            except Exception:  # noqa: BLE001 - reported to the user by the caller
                log.exception("پروژه خوانده نشد: %s", saved)
                return None
        return None

    def open_editor(self, row: int | None = None) -> None:
        """Fix words and reshape lines before the SRT is final.

        Works on any file that has been processed at some point, not only the
        one from this session: the WordStream is on disk.
        """
        project = None
        if row is None:
            rows = {index.row() for index in self.table.selectedIndexes()}
            row = min(rows) if rows else None
        if row is not None and row < len(self.queue):
            project = self._project_for(self.queue[row])
            if project is None:
                # Falling back to the last result here opened a different
                # video's subtitle under this file's name.
                QMessageBox.information(
                    self,
                    "ویرایش",
                    f"برای «{self.queue[row].name}» هنوز زیرنویسی ساخته نشده "
                    "(یا فایل پروژه‌اش خوانده نشد). اول همین فایل را پردازش کن.",
                )
                return
        else:
            project = self.last_project
        if project is None:
            QMessageBox.information(
                self,
                "ویرایش",
                "اول یک ویدیو را پردازش کن، بعد روی همان ردیف دابل‌کلیک کن.",
            )
            return

        dialog = EditorDialog(project, self.config, self)
        dialog.exec()

    def open_output_folder(self) -> None:
        if self.last_output is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output.parent)))
