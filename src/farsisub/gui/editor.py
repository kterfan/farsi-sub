"""Fix the subtitle before it is written out.

Everything here rests on one fact: the timing of a cue comes from the words
inside it, not from the cue itself. So splitting a cue, merging two, or moving
a word across the boundary all recompute their own times. Nothing drifts, and
there is no timeline to keep in sync by hand.

Editing the text never touches the timings at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QLineEdit,
    QStyledItemDelegate,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from ..config import AppConfig
from ..models import Cue, Project, Word
from ..render.segment import build_cues, wrap_lines
from ..render.writers import write_subtitle
from ..text.corrections import add_correction, correct_text, diff_pairs
from . import theme

COL_START, COL_END, COL_DURATION, COL_CPS, COL_TEXT = range(5)


def timecode(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, seconds), 60)
    return f"{int(minutes):02d}:{rest:05.2f}"


@dataclass
class EditableCue:
    """A cue plus the words it came from, so timing stays derivable."""

    words: list[Word]
    text: str = ""
    # The rendered line as it first appeared. Comparing against the raw model
    # words instead would flag the normaliser's own work (ZWNJ, Persian
    # digits, dropped commas) as if the user had changed it.
    original: str = ""
    # Set once the user types over the text; timings then stay as they are.
    edited: bool = False

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def cps(self) -> float:
        return len(self.text) / self.duration if self.duration > 0 else 0.0

    @property
    def worst_probability(self) -> float:
        return min((w.probability for w in self.words), default=1.0)

    def shaky_words(self, threshold: float) -> dict[str, float]:
        """Bare word -> probability, for the words the model doubted.

        Marking the whole line instead flagged 69% of lines on a real clip
        while only 9% of words were actually weak: the eye then has nowhere to
        go. The word carries the warning now.
        """
        out: dict[str, float] = {}
        for word in self.words:
            if word.probability >= threshold:
                continue
            bare = word.text.strip("،؛:.!؟…")
            if bare and word.probability < out.get(bare, 1.0):
                out[bare] = word.probability
        return out


def cues_to_editable(project: Project, cues: list[Cue]) -> list[EditableCue]:
    out: list[EditableCue] = []
    for cue in cues:
        start, end = cue.word_range or (0, 0)
        words = project.words[start:end]
        rendered = cue.text.replace("\n", " ")
        out.append(EditableCue(words=list(words), text=rendered, original=rendered))
    return out


class MarkingDelegate(QStyledItemDelegate):
    """Keeps track of the word the user highlighted while editing a line.

    Selecting text inside a table cell is only possible while its editor is
    open, and the selection is gone the moment the editor closes. So the
    selection is captured live and handed to the dialog, which is what makes
    "highlight a word, press the button" work.
    """

    def __init__(self, owner: "EditorDialog") -> None:
        super().__init__(owner)
        self.owner = owner

    def paint(self, painter, option, index):  # noqa: N802 - Qt naming
        """Draw the line with only its doubtful words coloured."""
        row = index.row()
        if row >= len(self.owner.cues):
            super().paint(painter, option, index)
            return

        cue = self.owner.cues[row]
        shaky = cue.shaky_words(self.owner.config.low_confidence)
        if not shaky:
            super().paint(painter, option, index)
            return

        from PySide6.QtGui import QTextDocument
        from PySide6.QtWidgets import QStyle

        palette = self.owner.palette_tokens
        very_low = self.owner.config.very_low_confidence

        parts = []
        for token in index.data() .split():
            bare = token.strip("،؛:.!؟…")
            probability = shaky.get(bare)
            if probability is None:
                parts.append(escape(token))
                continue
            colour = palette.danger if probability < very_low else palette.warn
            parts.append(
                f'<span style="color:{colour};font-weight:600">{escape(token)}</span>'
            )

        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setHtml(
            '<div style="color:%s" dir="rtl">%s</div>' % (palette.text, " ".join(parts))
        )

        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        painter.translate(option.rect.left() + 4, option.rect.top() + 4)
        document.setTextWidth(option.rect.width() - 8)
        document.drawContents(painter)
        painter.restore()

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt naming
        editor = QLineEdit(parent)
        row = index.row()
        editor.selectionChanged.connect(
            lambda e=editor, r=row: self.owner.remember_marked(e.selectedText(), r)
        )
        # Typing a ZWNJ depends on the keyboard layout, so the app provides it.
        for keys in ("Ctrl+Space", "Shift+Space"):
            shortcut = QShortcut(QKeySequence(keys), editor)
            shortcut.activated.connect(lambda e=editor: e.insert("\u200c"))
        self.owner.active_editor = editor
        editor.destroyed.connect(lambda: setattr(self.owner, "active_editor", None))
        return editor


class EditorDialog(QDialog):
    """Table of cues: fix the words, reshape the lines, then export."""

    def __init__(self, project: Project, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.config = config
        self.setWindowTitle("ویرایش زیرنویس")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 620)
        # Reading and retyping Persian for minutes on end is easier on a light
        # background; the rest of the app stays dark.
        self.palette_tokens = theme.LIGHT
        self.setStyleSheet(theme.stylesheet(theme.LIGHT))

        # Last word highlighted inside a cell, and which row it was in.
        self.marked_text = ""
        self.marked_row = -1
        self.last_edited_row = -1
        self.active_editor = None
        # Snapshots for undo. Deleting the wrong line used to be unrecoverable
        # short of closing the dialog without saving.
        self.history: list[list[EditableCue]] = []
        self.redo_stack: list[list[EditableCue]] = []

        # Checking a line used to mean opening the video in another player.
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.setSource(QUrl.fromLocalFile(str(project.video_path)))
        self.stop_at = 0.0
        self.player.positionChanged.connect(self._stop_at_cue_end)
        # Follow the video while editing: whatever line is selected, the
        # picture sits on it.
        self.follow_video = True

        cues = build_cues(project.words, config.profile, config.text)
        self.cues = cues_to_editable(project, cues)
        self._build()
        self._reload()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE * 3, theme.SPACE * 3, theme.SPACE * 3, theme.SPACE * 3)
        layout.setSpacing(theme.SPACE * 2)

        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        layout.addWidget(self.summary)

        self.video = QVideoWidget()
        self.video.setMinimumHeight(200)
        self.video.setMaximumHeight(300)
        self.player.setVideoOutput(self.video)
        layout.addWidget(self.video)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["شروع", "پایان", "مدت", "CPS", "متن"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.ROW_HEIGHT)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        for column in (COL_START, COL_END, COL_DURATION, COL_CPS):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)
        self.table.setItemDelegateForColumn(COL_TEXT, MarkingDelegate(self))
        self.table.itemChanged.connect(self._text_edited)
        self.table.currentCellChanged.connect(self._row_selected)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE * 2)

        self.split_button = QPushButton("تقسیم (Ctrl+Enter)")
        self.split_button.clicked.connect(self.split_selected)
        self.merge_button = QPushButton("ادغام با بعدی (Ctrl+M)")
        self.merge_button.clicked.connect(self.merge_selected)
        self.delete_button = QPushButton("حذف خط")
        self.delete_button.clicked.connect(self.delete_selected)
        self.continuous_box = QCheckBox("پخش پیوسته")
        self.continuous_box.setToolTip(
            "به‌جای ایستادن سر همان خط، ویدیو ادامه می‌دهد و تو همراهش می‌خوانی"
        )

        self.play_button = QPushButton("پخش این خط (Space)")
        self.play_button.setToolTip("صدای همین خط را از ویدیو پخش می‌کند")
        self.play_button.clicked.connect(self.play_selected)

        self.undo_button = QPushButton("واگرد (Ctrl+Z)")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("از نو")
        self.redo_button.setEnabled(False)
        self.redo_button.clicked.connect(self.redo)

        self.zwnj_button = QPushButton("نیم‌فاصله")
        self.zwnj_button.setToolTip(
            "نیم‌فاصله را داخل کلمه می‌گذارد: می‌رود، خونه‌دار.\n"
            "میان‌بر: Ctrl+Space یا Shift+Space"
        )
        self.zwnj_button.clicked.connect(self.insert_zwnj)

        self.glossary_button = QPushButton("افزودن اصلاح به دیکشنری")
        self.glossary_button.setToolTip(
            "کلمه‌ای که اصلاح کردی برای همه ویدیوهای بعدی هم اعمال می‌شود"
        )
        self.glossary_button.clicked.connect(self.teach_correction)

        self.export_button = QPushButton("ذخیره SRT")
        self.export_button.setObjectName("Primary")
        self.export_button.clicked.connect(self.export)

        buttons.addWidget(self.play_button)
        buttons.addWidget(self.continuous_box)
        buttons.addWidget(self.undo_button)
        buttons.addWidget(self.redo_button)
        buttons.addWidget(self.split_button)
        buttons.addWidget(self.merge_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.zwnj_button)
        buttons.addWidget(self.glossary_button)
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)

        for shortcut, slot in (
            ("Ctrl+Return", self.split_selected),
            ("Ctrl+M", self.merge_selected),
            ("Ctrl+S", self.export),
            ("F3", self.jump_to_suspect),
            ("Space", self.play_selected),
            ("Ctrl+Z", self.undo),
            ("Ctrl+Y", self.redo),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            self.addAction(action)

    # ----------------------------------------------------------------- table

    def _reload(self, keep_row: int | None = None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.cues))
        for row, cue in enumerate(self.cues):
            values = [
                timecode(cue.start),
                timecode(cue.end),
                f"{cue.duration:.1f}",
                f"{cue.cps:.0f}",
                cue.text,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column != COL_TEXT:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)

            # The doubtful words are coloured by the delegate; the tooltip
            # names them so the reason is never just a colour.
            shaky = cue.shaky_words(self.config.low_confidence)
            if shaky:
                listing = "، ".join(sorted(shaky))
                self.table.item(row, COL_TEXT).setToolTip(
                    "مدل به این کلمه‌ها مطمئن نیست: " + listing
                )

            cps_item = self.table.item(row, COL_CPS)
            if cue.cps > self.config.profile.max_cps:
                cps_item.setForeground(QBrush(QColor(self.palette_tokens.warn)))
                cps_item.setToolTip("سریع‌تر از چیزی است که خوانده شود")
        self.table.blockSignals(False)

        threshold = self.config.low_confidence
        total_words = sum(len(c.words) for c in self.cues)
        shaky = sum(
            1 for c in self.cues for w in c.words if w.probability < threshold
        )
        self.summary.setText(
            f"{len(self.cues)} خط | {shaky} کلمه مشکوک از {total_words} | "
            f"ویرایش متن زمان‌ها را تغییر نمی‌دهد"
        )
        if keep_row is not None and self.table.rowCount():
            row = max(0, min(keep_row, self.table.rowCount() - 1))
            self.table.setCurrentCell(row, COL_TEXT)

    def _current_row(self) -> int:
        row = self.table.currentRow()
        return row if row >= 0 else 0

    def _text_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != COL_TEXT:
            return
        cue = self.cues[item.row()]
        if cue.text != item.text().strip():
            self._snapshot()
        cue.text = item.text().strip()
        cue.edited = True
        self.last_edited_row = item.row()
        self._reload(keep_row=item.row())

    # -------------------------------------------------------------- playback

    def play_selected(self) -> None:
        """Play the audio of the current line and stop where it ends."""
        row = self._current_row()
        if row >= len(self.cues):
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            return
        cue = self.cues[row]
        self.stop_at = 0.0 if self.continuous_box.isChecked() else cue.end + 0.15
        self.player.setPosition(int(max(0.0, cue.start - 0.1) * 1000))
        self.player.play()

    def _row_selected(self, row: int, column: int, *_rest) -> None:
        """Park the video on the selected line without starting playback."""
        if not self.follow_video or row < 0 or row >= len(self.cues):
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            return  # do not fight an ongoing playback
        self.player.setPosition(int(max(0.0, self.cues[row].start) * 1000))

    def _stop_at_cue_end(self, position_ms: int) -> None:
        if self.stop_at and position_ms >= self.stop_at * 1000:
            self.player.pause()
            self.stop_at = 0.0

    # --------------------------------------------------------------- history

    def _snapshot(self) -> None:
        from copy import deepcopy

        self.history.append(deepcopy(self.cues))
        del self.history[:-50]  # a long session should not grow without bound
        self.redo_stack.clear()
        self._update_history_buttons()

    def undo(self) -> None:
        from copy import deepcopy

        if not self.history:
            return
        self.redo_stack.append(deepcopy(self.cues))
        self.cues = self.history.pop()
        self._reload()
        self._update_history_buttons()

    def redo(self) -> None:
        from copy import deepcopy

        if not self.redo_stack:
            return
        self.history.append(deepcopy(self.cues))
        self.cues = self.redo_stack.pop()
        self._reload()
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self.history))
        self.redo_button.setEnabled(bool(self.redo_stack))

    # ------------------------------------------------------------ operations

    def split_selected(self) -> None:
        self._snapshot()
        """Cut one line into two, each keeping the timing of its own words."""
        row = self._current_row()
        if row >= len(self.cues):
            return
        cue = self.cues[row]
        if len(cue.words) < 2:
            QMessageBox.information(self, "تقسیم", "این خط فقط یک کلمه دارد")
            return

        middle = len(cue.words) // 2
        first = EditableCue(words=cue.words[:middle])
        second = EditableCue(words=cue.words[middle:])
        first.text = first.original = " ".join(w.text for w in first.words)
        second.text = second.original = " ".join(w.text for w in second.words)
        self.cues[row : row + 1] = [first, second]
        self._reload(keep_row=row)

    def merge_selected(self) -> None:
        self._snapshot()
        """Join this line with the next; the times simply span both."""
        row = self._current_row()
        if row + 1 >= len(self.cues):
            return
        first, second = self.cues[row], self.cues[row + 1]
        merged = EditableCue(words=first.words + second.words)
        merged.text = f"{first.text} {second.text}".strip()
        merged.original = f"{first.original} {second.original}".strip()
        merged.edited = first.edited or second.edited
        self.cues[row : row + 2] = [merged]
        self._reload(keep_row=row)

    def delete_selected(self) -> None:
        self._snapshot()
        row = self._current_row()
        if row < len(self.cues):
            del self.cues[row]
            self._reload(keep_row=row)

    def jump_to_suspect(self) -> None:
        """Go to the next line the model was unsure about."""
        start = self._current_row() + 1
        order = list(range(start, len(self.cues))) + list(range(0, start))
        for row in order:
            if self.cues[row].shaky_words(self.config.low_confidence):
                self.table.setCurrentCell(row, COL_TEXT)
                return
        QMessageBox.information(self, "بررسی", "خط مشکوکی نمانده")

    def insert_zwnj(self) -> None:
        """Put a zero width non joiner where the cursor is."""
        editor = self.active_editor
        if editor is None:
            QMessageBox.information(
                self,
                "نیم‌فاصله",
                "اول روی متن دابل‌کلیک کن تا وارد ویرایش شوی، "
                "بعد نشانگر را جای نیم‌فاصله بگذار و این دکمه را بزن.",
            )
            return
        editor.insert("\u200c")
        editor.setFocus()

    def remember_marked(self, text: str, row: int) -> None:
        """Called while editing, every time the selection inside a cell changes."""
        cleaned = text.strip(" ‌" + "،؛:.!؟…")
        if cleaned:
            self.marked_text = cleaned
            self.marked_row = row

    def _pair_for_marked(self, heard: list[str], corrected: list[str]) -> tuple[str, str] | None:
        """Match the highlighted word with the word it replaced."""
        marked = self.marked_text
        if not marked or marked not in corrected:
            return None
        position = corrected.index(marked)
        candidates = diff_pairs(heard, corrected)
        for old, new in candidates:
            if new == marked:
                return old, new
        # Same word count: the replaced word sits at the same position.
        if len(heard) == len(corrected) and position < len(heard):
            old = heard[position].strip("،؛:.!؟…")
            if old and old != marked:
                return old, marked
        return None

    def teach_correction(self) -> None:
        """Save a fix so every future video applies it by itself.

        Highlight the corrected word and press the button: that exact word is
        stored. With nothing highlighted, every change on the line is offered
        instead. Nothing is ever saved without pressing this button.
        """
        row = self._current_row()
        # The line the user actually retyped wins over wherever the cursor
        # ended up after clicking the button.
        if self.marked_row >= 0 and self.marked_row < len(self.cues):
            row = self.marked_row
        elif self.last_edited_row >= 0 and self.last_edited_row < len(self.cues):
            row = self.last_edited_row
        if row >= len(self.cues):
            return
        cue = self.cues[row]

        heard = (cue.original or " ".join(w.text for w in cue.words)).split()
        corrected = cue.text.split()

        pair = self._pair_for_marked(heard, corrected) if self.marked_row == row else None
        pairs = [pair] if pair else diff_pairs(heard, corrected)

        if not pairs:
            QMessageBox.information(
                self,
                "دیکشنری",
                "اول کلمه را اصلاح کن (و اگر خواستی همان را انتخاب کن)، "
                "بعد این دکمه را بزن.",
            )
            return

        listing = "\n".join(f"«{a}»  ←  «{b}»" for a, b in pairs)
        source = "کلمه انتخاب‌شده" if pair else "همه تغییرهای این خط"
        answer = QMessageBox.question(
            self,
            "ذخیره در دیکشنری",
            f"{source}:\n\n{listing}\n\n"
            "برای همیشه ذخیره شود؟ از این به بعد در همه ویدیوها خودکار اعمال "
            "می‌شود و به مدل هم گفته می‌شود تا از اول درست بشنود.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        for heard_word, correct_word in pairs:
            path = add_correction(heard_word, correct_word)

        self._snapshot()
        applied = self._apply_to_all(dict(pairs))
        extra = f"\nهمین حالا روی {applied} خط این زیرنویس اعمال شد." if applied else ""
        QMessageBox.information(
            self,
            "ذخیره شد",
            f"ذخیره شد برای دفعات بعدی:\n\n{listing}{extra}\n\nمحل ذخیره:\n{path}",
        )
        self.marked_text = ""
        self.marked_row = -1

    def _apply_to_all(self, table: dict[str, str], skip_row: int = -1) -> int:
        """Apply a freshly learned correction across the whole subtitle.

        The edited line is included too: the same wrong word often appears
        twice in one line, and only the first was retyped by hand.
        """
        changed = 0
        for row, cue in enumerate(self.cues):
            fixed = correct_text(cue.text, table)
            if fixed != cue.text:
                cue.text = fixed
                cue.edited = True
                changed += 1
        if changed:
            self._reload(keep_row=skip_row)
        return changed

    # --------------------------------------------------------------- export

    def to_cues(self) -> list[Cue]:
        out: list[Cue] = []
        for index, cue in enumerate(self.cues, start=1):
            text = cue.text.strip()
            if not text:
                continue
            out.append(
                Cue(
                    index=index,
                    start=cue.start,
                    end=cue.end,
                    lines=wrap_lines(text, self.config.profile),
                )
            )
        return out

    def export(self) -> None:
        from ..pipeline import output_path
        from pathlib import Path

        target = output_path(Path(self.project.video_path), self.config, ".srt")
        write_subtitle(self.to_cues(), target, bom=self.config.text.bom)
        QMessageBox.information(self, "ذخیره شد", str(target))
        self.accept()
