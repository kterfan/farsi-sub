"""Main window: drop videos, watch them turn into subtitles.

Layout is right-to-left throughout, except for timecodes and file paths which
stay left-to-right because that is how they are actually read.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTime, QUrl
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
from .worker import Job, TranscribeWorker

VIDEO_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
}

STATUS_QUEUED = "در صف"
STATUS_RUNNING = "در حال پردازش"
STATUS_DONE = "آماده"
STATUS_FAILED = "خطا"


class DropZone(QFrame):
    """The empty state: never a blank window."""

    def __init__(self, on_files) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self._on_files = on_files

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE)
        title = QLabel("ویدیو را اینجا رها کن")
        title.setObjectName("Heading")
        title.setAlignment(Qt.AlignCenter)
        hint = QLabel("یا کلیک کن تا از سیستم انتخاب کنی — چند فایل هم می‌شود")
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(hint)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        paths, _ = QFileDialog.getOpenFileNames(self, "انتخاب ویدیو")
        if paths:
            self._on_files([Path(p) for p in paths])

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            self.setObjectName("DropZoneActive")
            self.setStyleSheet(self.styleSheet())  # force a repaint of the border
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setObjectName("DropZone")
        self.setStyleSheet(self.styleSheet())

    def dropEvent(self, event) -> None:  # noqa: N802
        self.setObjectName("DropZone")
        self.setStyleSheet(self.styleSheet())
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        wanted = [p for p in paths if p.suffix.lower() in VIDEO_SUFFIXES]
        if wanted:
            self._on_files(wanted)


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

        self.setWindowTitle("FarsiSub — زیرنویس فارسی")
        self.setLayoutDirection(Qt.RightToLeft)
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
        layout.addWidget(DropZone(self.add_files))
        layout.addWidget(self._options())
        layout.addWidget(self._table(), stretch=1)
        layout.addWidget(self._footer())

        self.setCentralWidget(root)
        self._shortcuts()

    def _header(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)

        title = QLabel("زیرنویس فارسی، کاملاً روی همین کامپیوتر")
        title.setObjectName("Heading")
        self.engine_label = QLabel()
        self.engine_label.setObjectName("Muted")

        row.addWidget(title)
        row.addStretch(1)
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

        row.addWidget(QLabel("سبک:"))
        row.addWidget(self.profile_box)
        row.addWidget(QLabel("مدل:"))
        row.addWidget(self.model_box)
        row.addWidget(self.merge_box)
        row.addWidget(self.digits_box)
        row.addWidget(self.period_box)
        row.addStretch(1)
        return card

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
        self.progress.setFormat("آماده")
        # The bar fills left-to-right; only the label inside it is Persian.
        self.progress.setLayoutDirection(Qt.LeftToRight)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")

        self.start_button = QPushButton("شروع")
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

        row.addWidget(self.progress, stretch=1)
        row.addWidget(self.status_label)
        row.addWidget(self.clear_button)
        row.addWidget(self.again_button)
        row.addWidget(self.edit_button)
        row.addWidget(self.open_button)
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
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
        paths, _ = QFileDialog.getOpenFileNames(self, "انتخاب ویدیو")
        if paths:
            self.add_files([Path(p) for p in paths])

    def add_files(self, paths: list[Path]) -> None:
        for path in paths:
            if path in self.queue:
                continue
            self.queue.append(path)
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(path.name)
            # File names are usually Latin: pin them to the visual left even
            # though the window itself is right-to-left.
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)
            name_item.setToolTip(str(path))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(STATUS_QUEUED))
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
            self.table.item(row, 2).setText("")
        self.progress.setValue(0)
        self.progress.setFormat("آماده")
        self._update_buttons()

    def remove_selected(self) -> None:
        if self.job is not None:
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.queue[row]
        self._update_buttons()

    def clear_queue(self) -> None:
        if self.job is not None:
            return
        self.table.setRowCount(0)
        self.queue.clear()
        self.last_output = None
        self.open_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("آماده")
        self.status_label.setText("")
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
        names = "، ".join(installed) if installed else "هیچ مدلی نصب نیست"
        self.engine_label.setText(
            f"موتور: {'آماده' if binary else 'پیدا نشد'} | مدل‌ها: {names}"
        )
        self._update_buttons()

    def _update_buttons(self) -> None:
        idle = self.job is None
        pending = any(
            self.table.item(row, 1).text() in (STATUS_QUEUED, STATUS_FAILED)
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

    def _set_status(self, path: Path, status: str, output: str = "") -> None:
        row = self._row_for(path)
        self.table.item(row, 1).setText(status)
        if output:
            self.table.item(row, 2).setText(output)

    # ---------------------------------------------------------------- queue

    def start_queue(self) -> None:
        if self.job is not None:
            return
        pending = [
            path
            for i, path in enumerate(self.queue)
            if self.table.item(i, 1).text() in (STATUS_QUEUED, STATUS_FAILED)
        ]
        if not pending:
            return
        self._run(pending[0])

    def _run(self, path: Path) -> None:
        self.started_at = time.time()
        self._set_status(path, STATUS_RUNNING)
        self.progress.setValue(0)
        self.progress.setFormat(f"{path.name} — %p%")

        # Which file this job is for; the slots below run later, on the GUI
        # thread, and need it.
        self.running_path = path

        worker = TranscribeWorker(path, self.config)
        # Bound methods with `self` as receiver, and QueuedConnection spelled
        # out. A lambda here has no receiver object, so Qt runs it on the
        # WORKER thread -- and touching a widget from there crashes the process
        # with an access violation. That is exactly what happened.
        worker.progress.connect(self._on_progress, Qt.QueuedConnection)
        worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        worker.failed.connect(self._on_failed, Qt.QueuedConnection)

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
        self.status_label.setText("")
        self.progress.setValue(100)
        self.progress.setFormat("انجام شد")

    def _on_failed(self, message: str) -> None:
        path = self.running_path
        if path is not None:
            self._set_status(path, STATUS_FAILED)
        self.status_label.setText("")
        self.progress.setFormat("خطا")
        if message != "لغو شد":
            QMessageBox.warning(self, "پردازش انجام نشد", message)

    def _job_finished(self) -> None:
        self.job = None
        self._update_buttons()
        self.start_queue()  # move on to the next file in the queue

    def cancel(self) -> None:
        if self.job is not None:
            self.job.worker.cancel()
            self.status_label.setText("در حال لغو…")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Never let the window die while a worker thread is still alive."""
        if self.job is not None:
            self.job.stop()
            self.job = None
        super().closeEvent(event)

    def refresh_models(self) -> None:
        """Public: re-read the models folder (a model may have just arrived)."""
        self._refresh_model_state()

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
            except Exception:
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
