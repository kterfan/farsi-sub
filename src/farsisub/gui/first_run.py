"""First launch on a fresh machine: pick a model and fetch it.

The installer deliberately ships without model weights, so this is the first
thing a new user sees. It has to work on a slow or interrupted connection,
which is why the download resumes and why importing a file copied over by hand
is offered right next to it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..engine import locate, modelstore
from . import theme


def describe_hardware() -> str:
    """What the engine will actually run on, in plain words."""
    if (locate.bin_dir() / "ggml-cuda.dll").exists():
        return "شتاب‌دهنده انویدیا نصب است — پردازش چند برابر سریع‌تر"
    return "پردازش روی CPU انجام می‌شود — کندتر ولی روی هر سیستمی کار می‌کند"


class DownloadWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, model_name: str) -> None:
        super().__init__()
        self.model_name = model_name
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        def report(state: modelstore.Progress) -> None:
            if self._cancelled:
                raise modelstore.DownloadError("لغو شد")
            done = state.downloaded / 1e9
            total = state.total / 1e9 if state.total else 0
            self.progress.emit(
                int(state.percent), f"{done:.2f} از {total:.2f} گیگابایت"
            )

        try:
            modelstore.download_model(self.model_name, on_progress=report)
        except modelstore.DownloadError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001
            self.failed.emit(f"دانلود ناموفق بود: {error}")
        else:
            self.finished.emit(self.model_name)


class FirstRunDialog(QDialog):
    """Choose a model, strongest first, and install it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("آماده‌سازی FarsiSub")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(720, 520)
        self.thread: QThread | None = None
        self.worker: DownloadWorker | None = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE * 4, theme.SPACE * 4, theme.SPACE * 4, theme.SPACE * 4)
        layout.setSpacing(theme.SPACE * 3)

        title = QLabel("یک مدل انتخاب کن")
        title.setObjectName("Heading")
        layout.addWidget(title)

        hint = QLabel(
            "برنامه بدون مدل کار نمی‌کند. مدل‌ها از قوی‌ترین به سبک‌ترین مرتب شده‌اند.\n"
            + describe_hardware()
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["مدل", "حجم", "کیفیت فارسی", "سرعت"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        installed = set(locate.installed_models())
        for info in modelstore.CATALOG:
            row = self.table.rowCount()
            self.table.insertRow(row)
            label = info.label + ("  (نصب شده)" if info.name in installed else "")
            cells = [label, f"{info.size_gb:.2f} GB", info.quality, info.speed]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if column:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
            self.table.item(row, 0).setData(Qt.UserRole, info.name)
            if info.note:
                self.table.item(row, 0).setToolTip(info.note)
        # Second row is the balanced one; it is the sensible default.
        # setCurrentCell, not selectRow: the latter leaves currentRow at -1 here.
        self.table.setCurrentCell(1 if self.table.rowCount() > 1 else 0, 0)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFormat("آماده")
        self.progress.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.import_button = QPushButton("وارد کردن از فایل")
        self.import_button.setToolTip(
            "اگر مدل را جداگانه دانلود کرده‌ای یا کسی روی فلش برایت آورده"
        )
        self.import_button.clicked.connect(self.import_model)

        self.download_button = QPushButton("دانلود و نصب")
        self.download_button.setObjectName("Primary")
        self.download_button.clicked.connect(self.start_download)

        self.close_button = QPushButton("بعداً")
        self.close_button.clicked.connect(self.reject)

        buttons.addWidget(self.import_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.download_button)
        layout.addLayout(buttons)

    # ------------------------------------------------------------- behaviour

    def selected_model(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    def start_download(self) -> None:
        name = self.selected_model()
        if not name or self.thread is not None:
            return
        if locate.model_path(name) is not None:
            QMessageBox.information(self, "نصب", "این مدل از قبل نصب است")
            self.accept()
            return

        self.download_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.status.setText("در حال دانلود… قطع شدن مشکلی ندارد، از همان‌جا ادامه می‌دهد")

        worker = DownloadWorker(name)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Bound methods with an explicit queued connection: a lambda here would
        # run on the download thread and touch widgets from there.
        worker.progress.connect(self._on_progress, Qt.QueuedConnection)
        worker.finished.connect(self._on_finished, Qt.QueuedConnection)
        worker.failed.connect(self._on_failed, Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self.worker, self.thread = worker, thread
        thread.start()

    def _on_progress(self, percent: int, detail: str) -> None:
        self.progress.setValue(percent)
        self.progress.setFormat("%p%")
        self.status.setText(detail)

    def _on_finished(self, name: str) -> None:
        self.thread = self.worker = None
        QMessageBox.information(self, "آماده شد", f"مدل «{name}» نصب شد")
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.thread = self.worker = None
        self.download_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.status.setText("")
        QMessageBox.warning(
            self,
            "دانلود انجام نشد",
            f"{message}\n\nمی‌توانی دوباره تلاش کنی، یا مدل را جداگانه "
            "دانلود کرده و با دکمه «وارد کردن از فایل» نصب کنی.",
        )

    def import_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل مدل", "", "مدل ggml (*.bin)"
        )
        if not path:
            return
        try:
            target = modelstore.import_model_file(Path(path))
        except modelstore.DownloadError as error:
            QMessageBox.warning(self, "وارد کردن انجام نشد", str(error))
            return
        QMessageBox.information(self, "نصب شد", str(target))
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.worker is not None:
            self.worker.cancel()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(5000)
        super().closeEvent(event)
