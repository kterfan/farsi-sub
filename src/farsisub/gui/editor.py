"""Fix the subtitle before it is written out.

Everything here rests on one fact: the timing of a cue comes from the words
inside it, not from the cue itself. So splitting a cue, merging two, or moving
a word across the boundary all recompute their own times. Nothing drifts, and
there is no timeline to keep in sync by hand.

Editing the text never touches the timings at all.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, QSizeF, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QMenu,
    QProgressDialog,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QLineEdit,
    QSlider,
    QSplitter,
    QStyledItemDelegate,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import json
import logging
import os

from ..config import BUILTIN_PROFILES, AppConfig
from ..fileio import atomic_write_text
from ..models import Cue, EditedLine, Project, Word
from ..render.segment import build_cues, cues_from_lines
from ..render.writers import write_subtitle
from ..text.corrections import add_correction, correct_text, diff_pairs
from ..text.normalize import to_persian_digits
from . import theme
from .widgets import ActionButton, ResponsiveRow, Segment, ToggleSwitch
from .editor_tools import (
    BurnWorker,
    EnvelopeWorker,
    FindReplaceDialog,
    WaveformStrip,
    move_edge,
    replace_in_cues,
    replace_in_text,
)

COL_START, COL_END, COL_DURATION, COL_CPS, COL_TEXT = range(5)

# The nudge stops as soon as a frame is actually on screen; this is only the
# fallback for a file that never delivers one. A fixed short timer was not
# enough: a 1080x1920 HEVC frame did not finish decoding in 60 ms, and the
# picture stayed black on the line the user had just picked.
NUDGE_TIMEOUT_MS = 600

# Taller than the queue's rows: these are read, retyped and read again.
EDITOR_ROW = 44

PLAY_LABEL = "پخش خط"
PAUSE_LABEL = "توقف"

log = logging.getLogger(__name__)


def video_enabled() -> bool:
    """Playback can be switched off when a codec takes the process down.

    Qt hands decoding to a native backend, and a bad file there kills the
    whole app without raising anything Python can catch. The editor is the
    important part; the picture is a convenience.
    """
    return os.environ.get("FARSISUB_NO_VIDEO", "") != "1"


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


def saved_to_editable(project: Project) -> list[EditableCue]:
    """Rebuild the editor's lines from what was saved with the project."""
    stream = project.words
    out: list[EditableCue] = []
    for line in project.lines:
        words = [stream[i] for i in line.words if 0 <= i < len(stream)]
        if not words:
            continue
        out.append(EditableCue(words=words, text=line.text, original=line.text,
                               edited=line.edited))
    return out


def bare_word(text: str) -> str:
    """A token stripped of what the eye ignores when comparing two lines."""
    return text.strip("،؛:.!؟…‌").replace("‌", "")


def _move_token(source: str, target: str, down: bool) -> tuple[str, str] | None:
    """Move the last (down) or first (up) token of one line onto the other.

    None when the source would be left with no text at all.
    """
    tokens = source.split()
    if len(tokens) < 2:
        return None
    if down:
        return " ".join(tokens[:-1]), f"{tokens[-1]} {target}".strip()
    return " ".join(tokens[1:]), f"{target} {tokens[0]}".strip()


def split_text(text: str, cut: int, of: int) -> tuple[str, str]:
    """Split a line's text where its words are split: `cut` words out of `of`.

    The text shown is what gets split, never the raw model words: rebuilding
    from those threw away the user's corrections and the writing rules
    (Persian digits, dropped commas, ZWNJ). When the text no longer lines up
    with the words one for one, it is cut at the same share of the line.
    """
    tokens = text.split()
    if len(tokens) < 2:
        return text.strip(), ""
    at = cut if len(tokens) == of else round(cut / max(of, 1) * len(tokens))
    at = max(1, min(at, len(tokens) - 1))
    return " ".join(tokens[:at]), " ".join(tokens[at:])


def cue_index_at(cues: list[EditableCue], starts: list[float], seconds: float) -> int:
    """Row of the cue the playhead sits inside, or -1 in the silence between.

    `starts` is kept alongside instead of rebuilt here: this runs on every
    positionChanged, a few times a second. The row is what the caller needs --
    looking the cue up again by value would match the wrong twin, since two
    cues with the same words and text compare equal.
    """
    index = bisect_right(starts, seconds) - 1
    if index < 0 or index >= len(cues):
        return -1
    return index if seconds < cues[index].end else -1



class VideoStage(QGraphicsView):
    """The picture, with the current line drawn on top of it.

    A label laid over a QVideoWidget was invisible on Windows: the backend
    paints the video onto its own surface, above every child widget. Putting
    the picture and the text in one scene is the only way the caption stays in
    front of the frame.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#000000")))
        self.setMinimumHeight(120)

        self.audio_only = False
        self.item = QGraphicsVideoItem()
        self.scene().addItem(self.item)
        self.caption = QGraphicsTextItem()
        self.caption.setZValue(1)
        self.caption.setVisible(False)
        self.scene().addItem(self.caption)
        self.hint = QGraphicsTextItem()
        self.hint.setZValue(1)
        self.hint.setVisible(False)
        self.scene().addItem(self.hint)
        self.item.nativeSizeChanged.connect(self._native_size_changed)

    # The frame decides the scene: everything else is measured against it.
    def _native_size_changed(self, size) -> None:
        self.set_frame_size(size)

    def set_frame_size(self, size) -> None:
        """Give the item the real frame size, from the signal or the metadata.

        Left at its default the item is a 320x240 box, and a portrait video is
        squeezed into it.
        """
        if size is None or size.isEmpty():
            return
        if self.item.size() == size:
            return
        self.item.setSize(size)
        self.scene().setSceneRect(self.item.boundingRect())
        self._fit()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self.item.size().isEmpty():
            return
        self.fitInView(self.item, Qt.KeepAspectRatio)
        self._place_caption()

    def set_audio_only(self, note: str = "") -> None:
        """No picture to show: give the caption a stage of its own.

        An audio file is a first-class input, so the editor still needs a
        surface for the line being read.
        """
        self.audio_only = True
        self.set_frame_size(QSizeF(960, 540))
        self.hint.setPlainText(note or "فقط صدا")
        font = QFont()
        font.setFamilies([theme.FONT_FAMILY, theme.FONT_FALLBACK])
        font.setPixelSize(28)
        self.hint.setFont(font)
        self.hint.setDefaultTextColor(QColor("#64748B"))
        self.hint.setVisible(True)
        self._place_caption()

    def set_caption(self, text: str) -> None:
        if not text:
            self.caption.setVisible(False)
            return
        frame = self.item.size()
        # The text is measured in frame pixels, so it keeps the same share of
        # the picture at every window size -- about what a burned-in subtitle
        # takes up. Setting it on the item, not in the HTML: a font-size in the
        # markup came out at the document default and was unreadably small.
        side = min(frame.width() or 640, frame.height() or 480)
        font = QFont()
        font.setFamilies([theme.FONT_FAMILY, theme.FONT_FALLBACK])
        font.setPixelSize(max(14, int(side * 0.045)))
        font.setBold(True)
        self.caption.setFont(font)
        self.caption.setHtml(
            '<div dir="rtl" align="center" style="color:#ffffff;'
            f'background-color:rgba(0,0,0,150);">{escape(text)}</div>'
        )
        self.caption.setVisible(True)
        self._place_caption()

    def _place_caption(self) -> None:
        if self.item.size().isEmpty():
            return
        frame = self.item.size()
        if self.hint.isVisible():
            box = self.hint.boundingRect()
            self.hint.setPos((frame.width() - box.width()) / 2, frame.height() * 0.18)
        if not self.caption.isVisible():
            return
        self.caption.setTextWidth(frame.width() * 0.9)
        box = self.caption.boundingRect()
        # With no picture the line belongs in the middle, not pinned to the
        # bottom edge of an empty rectangle.
        top = (
            (frame.height() - box.height()) / 2
            if self.audio_only
            else frame.height() - box.height() - frame.height() * 0.06
        )
        self.caption.setPos((frame.width() - box.width()) / 2, top)


class SeekSlider(QSlider):
    """Clicking the groove jumps there, instead of stepping one page."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            span = max(self.width() - 1, 1)
            fraction = event.position().x() / span
            if self.layoutDirection() == Qt.RightToLeft:
                fraction = 1.0 - fraction
            value = self.minimum() + round(fraction * (self.maximum() - self.minimum()))
            self.setValue(int(value))
            self.sliderMoved.emit(int(value))
            event.accept()
            return
        super().mousePressEvent(event)


class RowMarkDelegate(QStyledItemDelegate):
    """A bar at the start of the row the user is on.

    The selected row is only a light tint, which is easy to lose in a long
    list while the video moves it; the bar gives the eye a fixed mark.
    """

    def paint(self, painter, option, index):  # noqa: N802 - Qt naming
        from PySide6.QtWidgets import QStyle

        super().paint(painter, option, index)
        if not option.state & QStyle.State_Selected:
            return
        tokens = theme.tokens_for(option.widget)
        rect = option.rect
        rtl = option.direction == Qt.RightToLeft
        x = rect.right() - 3 if rtl else rect.left()
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tokens.accent))
        painter.drawRoundedRect(x, rect.top() + 6, 4, rect.height() - 12, 2, 2)
        painter.restore()


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

    PAD = 8
    PAD_X = 12

    def _document(self, option, index):
        """The line as it is drawn: wrapped, right to left, doubts coloured.

        Every line goes through this, not just the doubtful ones. The default
        painter puts an ellipsis on anything too long, so a two-line cue was
        cut off mid-sentence -- exactly the cue that needs splitting and so
        exactly the one that has to be readable.
        """
        from PySide6.QtGui import QTextDocument

        row = index.row()
        cue = self.owner.cues[row] if row < len(self.owner.cues) else None
        shaky = cue.shaky_words(self.owner.config.low_confidence) if cue else {}
        palette = self.owner.palette_tokens
        very_low = self.owner.config.very_low_confidence

        # The selected row is only a tint now, so every colour stays the one
        # it has everywhere else: no second set of "on blue" shades to keep.
        base = palette.text
        keywords = self.owner.keyword_texts(cue) if cue else set()
        parts = []
        for token in (index.data() or "").split():
            bare = token.strip("،؛:.!؟…")
            probability = shaky.get(bare)
            if probability is None:
                if bare in keywords:
                    # Underlined as well: colour is never the only signal.
                    parts.append(
                        f'<span style="color:{palette.keyword};font-weight:700;text-decoration:underline">'
                        f"{escape(token)}</span>"
                    )
                else:
                    parts.append(escape(token))
                continue
            colour = palette.danger if probability < very_low else palette.warn
            parts.append(
                f'<span style="color:{colour};font-weight:700">{escape(token)}</span>'
            )

        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setDocumentMargin(0)
        document.setHtml(
            '<div style="color:%s" dir="rtl">%s</div>' % (base, " ".join(parts))
        )
        document.setTextWidth(max(option.rect.width() - 2 * self.PAD_X, 40))
        return document

    def sizeHint(self, option, index):  # noqa: N802 - Qt naming
        """Rows grow to fit the wrapped line instead of clipping it."""
        document = self._document(option, index)
        height = int(document.size().height()) + 2 * self.PAD
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(height, EDITOR_ROW))

    def paint(self, painter, option, index):  # noqa: N802 - Qt naming
        """Draw the line with only its doubtful words coloured."""
        from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

        document = self._document(option, index)

        # The row's own background -- hover, selection, the hairline under
        # it -- comes from the style sheet, exactly as in the other columns.
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, background, painter, widget)

        painter.save()
        top = option.rect.top() + max(self.PAD, (option.rect.height() - document.size().height()) / 2)
        painter.translate(option.rect.left() + self.PAD_X, top)
        document.drawContents(painter)
        painter.restore()

    def createEditor(self, parent, option, index):  # noqa: N802 - Qt naming
        editor = QLineEdit(parent)
        editor.setProperty("cue_row", index.row())
        editor.selectionChanged.connect(self._selection_changed)
        # Typing a ZWNJ depends on the keyboard layout, so the app provides it.
        for keys in ("Ctrl+Space", "Shift+Space"):
            shortcut = QShortcut(QKeySequence(keys), editor)
            shortcut.activated.connect(self._insert_zwnj)
        self.owner.editor_opened(editor)
        return editor

    def _selection_changed(self) -> None:
        """Which editor sent this is read from the signal, not from a closure.

        The row captured in a lambda goes stale the moment a line is split or
        merged, and the closure keeps the dead editor alive as well.
        """
        editor = self.sender()
        if isinstance(editor, QLineEdit):
            row = editor.property("cue_row")
            if row is not None:
                self.owner.remember_marked(editor.selectedText(), int(row))

    def _insert_zwnj(self) -> None:
        shortcut = self.sender()
        editor = shortcut.parent() if shortcut is not None else None
        if isinstance(editor, QLineEdit):
            editor.insert("\u200c")


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
        self._times_history: list[list] = []
        self._times_redo: list[list] = []

        # Checking a line used to mean opening the video in another player.
        self.player = None
        self.video = None
        self.slider = None
        self.clock = None
        self.video_pane = None
        # Where the picture sits, and whether the user said so themselves.
        self.video_side = False
        self.video_side_chosen = False
        self._saved_state: dict = {}
        self._finished = False
        # Whether the lines are the user's own. Until then the style stays in
        # charge: saving the auto-built lines on every close froze the layout,
        # and switching to another style later changed nothing in here.
        self.shaped = bool(project.lines)
        # A keyword or a word's time changed by hand: the project has to be
        # written even if the lines themselves were left to the style.
        self.words_touched = False
        self.wave = None
        self.wave_thread: QThread | None = None
        self.burn_thread: QThread | None = None
        self.stop_at = 0.0
        # A seek before the media is loaded is silently dropped, so it is kept
        # here and replayed the moment the player reports LoadedMedia.
        self.media_ready = False
        self.pending_seek: float | None = None
        self.pending_play = False
        self.nudging = False
        self.last_seek_row = -1
        # True while the table is being moved by the video, so the two do not
        # chase each other.
        self.following = False
        self._cue_starts: list[float] = []
        self._setup_player(Path(project.video_path))

        if project.lines:
            # Someone has already shaped this subtitle by hand; their lines
            # win over anything the style would build now.
            self.cues = saved_to_editable(project)
            log.info("خط‌های ویرایش‌شده از پروژه خوانده شد: %d", len(self.cues))
        else:
            cues = build_cues(project.words, config.profile, config.text)
            self.cues = cues_to_editable(project, cues)
        self._build()
        self._restore_ui_state()
        self._start_waveform(Path(project.video_path))
        self._reload()
        if self.cues:
            self.table.setCurrentCell(0, COL_TEXT)

    def _setup_player(self, video: Path) -> None:
        """Build the player, or carry on without one."""
        if not video_enabled():
            log.info("پخش ویدیو با تنظیم محیطی خاموش است")
            return
        if not video.exists():
            log.info("فایل ویدیو کنار پروژه نیست: %s", video)
            return

        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            log.info("آماده‌سازی پخش برای %s", video.name)
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
            self.video = VideoStage()
            self.player.setVideoOutput(self.video.item)
            # Frames are delivered on the backend's own thread, so this one is
            # queued: pausing the player from there is not allowed.
            self.video.item.videoSink().videoFrameChanged.connect(
                self._frame_arrived, Qt.QueuedConnection
            )
            self.player.errorOccurred.connect(self._media_error)
            self.player.positionChanged.connect(self._position_changed)
            self.player.durationChanged.connect(self._duration_changed)
            self.player.playbackStateChanged.connect(self._playback_state_changed)
            self.player.mediaStatusChanged.connect(self._media_status)
            self.player.setSource(QUrl.fromLocalFile(str(video)))
            log.info("پخش آماده شد")
        except Exception as error:  # noqa: BLE001 - the editor must still open
            log.warning("پخش در دسترس نیست: %s", error)
            self.player = None
            self.video = None

    def _media_error(self, error, message: str = "") -> None:
        log.warning("خطای پخش: %s %s", error, message)

    def _media_status(self, status) -> None:
        """A seek only lands once the media is loaded; until then it waits."""
        from PySide6.QtMultimedia import QMediaPlayer

        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            if not self.media_ready:
                self.media_ready = True
                log.info("رسانه آماده شد")
                self._place_video_by_shape()
            if self.pending_seek is not None:
                seconds, self.pending_seek = self.pending_seek, None
                play, self.pending_play = self.pending_play, False
                self._seek(seconds, play=play)
        elif status == QMediaPlayer.InvalidMedia:
            self.media_ready = False
            log.warning("رسانه خوانده نشد: %s", self.project.video_path)

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE * 4, theme.SPACE * 4, theme.SPACE * 4, theme.SPACE * 4)
        layout.setSpacing(theme.SPACE * 3)

        self._build_table()
        self._build_actions()
        layout.addWidget(self._header())
        layout.addWidget(self._command_bar())

        # The picture and the table share the window, and the user decides how.
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(True)
        layout.addWidget(self.splitter, stretch=1)
        if self.video is not None:
            self.video_pane = self._video_pane()
            self.splitter.addWidget(self.video_pane)
        else:
            # No picture: the transport controls have nowhere to live, and
            # without a player they would do nothing anyway.
            for widget in (self.play_button, self.continuous_box, self.side_button):
                widget.setParent(self)
                widget.hide()
        self.splitter.addWidget(self.table_pane)
        self.splitter.setStretchFactor(self.splitter.indexOf(self.table_pane), 1)

        # Space, Ctrl+Z and Ctrl+Y are swallowed before the key ever reaches a
        # cell editor, so typing a space used to start playback and Ctrl+Z used
        # to undo the whole line instead of the last letter. They are switched
        # off while an editor is open.
        self.editing_shortcuts: list[QAction] = []
        for shortcut, slot in (
            ("Ctrl+Return", self.split_selected),
            ("Ctrl+M", self.merge_selected),
            ("Ctrl+S", self.export),
            ("F3", self.jump_to_suspect),
            ("Space", self.play_selected),
            ("Ctrl+Z", self.undo),
            ("Ctrl+Y", self.redo),
            ("Alt+Down", self.move_word_down),
            ("Alt+Up", self.move_word_up),
            ("Ctrl+H", self.find_replace),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            self.addAction(action)
            if shortcut in ("Space", "Ctrl+Z", "Ctrl+Y"):
                self.editing_shortcuts.append(action)

    def _build_table(self) -> None:
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["شروع", "پایان", "مدت", "CPS", "متن"])
        self.table.horizontalHeaderItem(COL_TEXT).setToolTip(
            "دابل‌کلیک کن و بنویس. ویرایش متن زمان‌ها را تغییر نمی‌دهد."
        )
        self.table.horizontalHeaderItem(COL_CPS).setToolTip("حرف در ثانیه: هرچه بیشتر، سخت‌تر خوانده می‌شود")
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(EDITOR_ROW)
        # A wrapped two-line cue needs the room; Qt asks the delegate per row.
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Hairlines between rows instead of stripes: the coloured words and
        # the selected row both read better on one plain background.
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.NoFrame)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for column in (COL_START, COL_END, COL_DURATION, COL_CPS):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)
        delegate = MarkingDelegate(self)
        delegate.closeEditor.connect(self.editor_closed)
        self.table.setItemDelegateForColumn(COL_TEXT, delegate)
        self.table.setItemDelegateForColumn(COL_START, RowMarkDelegate(self))
        self.table.itemChanged.connect(self._text_edited)
        self.table.currentCellChanged.connect(self._row_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)

        # The waveform sits on the table, so moving an edge and reading the
        # line it belongs to happen in one place.
        self.table_pane = QWidget()
        self.table_pane.setObjectName("Bare")
        pane = QVBoxLayout(self.table_pane)
        pane.setContentsMargins(0, 0, 0, 0)
        pane.setSpacing(theme.SPACE * 2)
        if Path(self.project.video_path).exists():
            self.wave = WaveformStrip()
            self.wave.setToolTip(
                "موج صدای اطراف خط انتخاب‌شده. لبه آبی را بکش تا شروع یا پایان خط جابه‌جا شود؛\n"
                "جای دیگر کلیک کنی ویدیو به همان لحظه می‌رود."
            )
            self.wave.edge_moved.connect(self._edge_moved)
            self.wave.seek.connect(self._wave_seek)
            pane.addWidget(self.wave)
        card = QFrame()
        card.setObjectName("Card")
        inside = QVBoxLayout(card)
        inside.setContentsMargins(theme.SPACE, theme.SPACE, theme.SPACE, theme.SPACE)
        inside.addWidget(self.table)
        pane.addWidget(card, stretch=1)

    def _build_actions(self) -> None:
        """Every command, built once; where each one sits is decided later."""
        self.split_button = ActionButton("تقسیم", "split", priority=3)
        self.split_button.setToolTip(
            "این خط را دو تکه کن — Ctrl+Enter\n"
            "نشانگر را داخل متن هر جا بگذاری، از همان‌جا تقسیم می‌شود"
        )
        self.split_button.clicked.connect(self.split_selected)
        self.merge_button = ActionButton("ادغام", "merge", priority=3)
        self.merge_button.setToolTip("با خط بعدی یکی کن — Ctrl+M")
        self.merge_button.clicked.connect(self.merge_selected)
        self.delete_button = ActionButton("حذف", "trash", priority=3)
        self.delete_button.setToolTip("این خط را بردار")
        self.delete_button.clicked.connect(self.delete_selected)

        # Style switch with an instant preview: rendering costs nothing.
        self.style_box = QComboBox()
        for name, profile in BUILTIN_PROFILES.items():
            self.style_box.addItem(profile.label, name)
        if self.config.custom_profile is not None:
            self.style_box.addItem(self.config.custom_profile.label, self.config.custom_profile.name)
        self.style_box.setCurrentIndex(max(0, self.style_box.findData(self.config.profile.name)))
        self.style_box.setToolTip("سبک زیرنویس؛ همین‌جا عوضش کن و روی ویدیو ببین")
        self.style_box.currentIndexChanged.connect(self._style_changed)

        self.find_button = ActionButton("جایگزینی", "search", priority=2)
        self.find_button.setToolTip("یک کلمه را در همه خط‌ها عوض کن — Ctrl+H")
        self.find_button.clicked.connect(self.find_replace)

        self.burn_button = ActionButton("ویدیو با زیرنویس", "film", priority=1)
        self.burn_button.setToolTip(
            "زیرنویس را روی خود تصویر می‌نشاند و یک MP4 تازه می‌سازد؛\n"
            "برای اینستاگرام و جاهایی که فایل زیرنویس جدا نمی‌گیرند"
        )
        self.burn_button.setEnabled(Path(self.project.video_path).exists())
        self.burn_button.clicked.connect(self.burn_video)

        self.continuous_box = ToggleSwitch("پخش پیوسته")
        self.continuous_box.setToolTip(
            "به‌جای ایستادن سر همان خط، ویدیو ادامه می‌دهد و تو همراهش می‌خوانی"
        )

        self.play_button = ActionButton(PLAY_LABEL, "play", name="Round", icon_only=True)
        self.play_button.setIconSize(QSize(20, 20))
        self.play_button.setToolTip("همین خط را از ویدیو پخش می‌کند — Space")
        self.play_button.clicked.connect(self.play_selected)

        self.side_button = ActionButton("تصویر کنار", "columns", name="Quiet", icon_only=True)
        self.side_button.setToolTip(
            "تصویر را کنار جدول می‌برد یا برمی‌گرداند بالا.\n"
            "ویدیوی عمودی کنار جدول بزرگ‌تر دیده می‌شود."
        )
        self.side_button.setEnabled(self.video is not None)
        self.side_button.clicked.connect(self.toggle_video_side)

        self.undo_button = ActionButton("واگرد", "undo", icon_only=True)
        self.undo_button.setToolTip("آخرین تغییر را برگردان — Ctrl+Z")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = ActionButton("از نو", "redo", icon_only=True)
        self.redo_button.setToolTip("همان تغییر را دوباره بگذار — Ctrl+Y")
        self.redo_button.setEnabled(False)
        self.redo_button.clicked.connect(self.redo)

        self.word_down_button = ActionButton("کلمه به خط بعد", "word-down", priority=1)
        self.word_down_button.setToolTip(
            "آخرین کلمه این خط را با زمانش می‌برد اول خط بعدی — Alt+Down"
        )
        self.word_down_button.clicked.connect(self.move_word_down)
        self.word_up_button = ActionButton("کلمه به خط قبل", "word-up", priority=1)
        self.word_up_button.setToolTip(
            "اولین کلمه این خط را با زمانش می‌برد آخر خط قبلی — Alt+Up"
        )
        self.word_up_button.clicked.connect(self.move_word_up)

        self.zwnj_button = ActionButton("نیم‌فاصله", "space", priority=2)
        self.zwnj_button.setToolTip(
            "نیم‌فاصله را داخل کلمه می‌گذارد: می‌رود، خونه‌دار.\n"
            "میان‌بر: Ctrl+Space یا Shift+Space"
        )
        self.zwnj_button.clicked.connect(self.insert_zwnj)

        self.glossary_button = ActionButton("دیکشنری", "book", priority=2)
        self.glossary_button.setToolTip(
            "کلمه‌ای که اصلاح کردی برای همه ویدیوهای بعدی هم اعمال می‌شود"
        )
        self.glossary_button.clicked.connect(self.teach_correction)

        self.export_button = ActionButton(
            f"ذخیره {self.config.suffix.lstrip('.').upper()}", "save", name="Primary", collapsible=False
        )
        self.export_button.setToolTip("زیرنویس را کنار ویدیو ذخیره می‌کند — Ctrl+S")
        self.export_button.clicked.connect(self.export)

    def _header(self) -> QWidget:
        """Which file this is, what is left to check, and the way out.

        Saving lives up here, at the end of the reading direction, where a
        finished page is left -- and the row wraps instead of ever hiding it.
        """
        row = ResponsiveRow(spacing=theme.SPACE * 3)

        titles = QWidget()
        titles.setObjectName("Bare")
        column = QVBoxLayout(titles)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        caption = QLabel("ویرایش زیرنویس")
        caption.setObjectName("Caption")
        name = QLabel()
        name.setObjectName("Title")
        filename = Path(self.project.video_path).name
        # Measured against the face the label will really use.
        name.setText("\u2066" + name.fontMetrics().elidedText(filename, Qt.ElideMiddle, 300) + "\u2069")
        name.setToolTip(str(self.project.video_path))
        column.addWidget(caption)
        column.addWidget(name)
        row.add(titles)

        self.position_chip = QLabel()
        self.position_chip.setObjectName("Chip")
        row.add(self.position_chip)
        self.suspect_button = ActionButton("", "alert", name="ChipWarn", collapsible=False)
        self.suspect_button.setIconSize(QSize(14, 14))
        self.suspect_button.clicked.connect(self.jump_to_suspect)
        row.add(self.suspect_button)

        row.add_stretch()
        row.add(self.style_box)
        row.add(self.burn_button)
        row.add(self.export_button)
        self.header_row = row
        return row

    def _command_bar(self) -> QWidget:
        """The editing commands, grouped by what they act on.

        The old toolbar put whatever did not fit behind an overflow arrow, so
        on a laptop screen most of these were simply gone. This row drops the
        labels first and then wraps: every command stays one click away.
        """
        bar = ResponsiveRow()
        for group in (
            (self.undo_button, self.redo_button),
            (self.split_button, self.merge_button, self.delete_button),
            (self.word_up_button, self.word_down_button),
            (self.zwnj_button, self.glossary_button, self.find_button),
        ):
            bar.add(Segment(*group))
        self.command_bar = bar
        return bar

    def _video_pane(self) -> QWidget:
        """The picture in a card, with its scrub bar and transport under it."""
        pane = QFrame()
        pane.setObjectName("Card")
        column = QVBoxLayout(pane)
        column.setContentsMargins(theme.SPACE * 2, theme.SPACE * 2, theme.SPACE * 2, theme.SPACE * 2)
        column.setSpacing(theme.SPACE * 2)
        column.addWidget(self.video, stretch=1)

        scrub = QHBoxLayout()
        scrub.setSpacing(theme.SPACE * 2)
        self.slider = SeekSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setLayoutDirection(Qt.LeftToRight)
        self.slider.sliderMoved.connect(self._slider_moved)
        self.clock = QLabel(f"{timecode(0)} / {timecode(0)}")
        self.clock.setObjectName("Clock")
        self.clock.setLayoutDirection(Qt.LeftToRight)
        scrub.addWidget(self.slider, stretch=1)
        scrub.addWidget(self.clock)
        column.addLayout(scrub)

        # Play in the middle, the two settings either side of it: the shape
        # every media player has taught the hand to expect. The side button
        # gets the switch's width so the play button really is centred.
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.continuous_box)
        controls.addStretch(1)
        controls.addWidget(self.play_button)
        controls.addStretch(1)
        balance = QWidget()
        balance.setObjectName("Bare")
        balance.setMinimumWidth(self.continuous_box.sizeHint().width())
        holder = QHBoxLayout(balance)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addStretch(1)
        holder.addWidget(self.side_button)
        controls.addWidget(balance)
        column.addLayout(controls)
        return pane

    # ------------------------------------------------------- video placement

    def _place_video_by_shape(self) -> None:
        """A portrait video on top is mostly black bars; beside, it fills.

        Only a guess about the shape of the file -- the moment the user picks a
        side themselves, that choice wins and is remembered.
        """
        if self.video is None or self.video_side_chosen:
            return
        from PySide6.QtMultimedia import QMediaMetaData

        size = self.player.metaData().value(QMediaMetaData.Resolution)
        if size is None or not size.isValid() or size.width() <= 0:
            # An audio file: keep the stage on top and let it carry the text.
            self.video.set_audio_only(Path(self.project.video_path).name)
            self._arrange_video(side=False)
            return
        self.video.set_frame_size(QSizeF(size))
        self._arrange_video(side=size.height() > size.width())

    def _arrange_video(self, side: bool) -> None:
        if self.video is None:
            return
        self.video_side = side
        if side:
            # The table keeps index 0, so right-to-left puts it on the right --
            # the reading side -- and the picture goes to the left.
            self.splitter.setOrientation(Qt.Horizontal)
            self.splitter.insertWidget(1, self.video_pane)
            whole = max(self.splitter.width(), 1)
            sizes = [int(whole * 0.62), int(whole * 0.38)]
        else:
            self.splitter.setOrientation(Qt.Vertical)
            self.splitter.insertWidget(0, self.video_pane)
            whole = max(self.splitter.height(), 1)
            sizes = [int(whole * 0.38), int(whole * 0.62)]
        kept = [int(s) for s in self._saved_state.get("splitter_side" if side else "splitter_top", [])]
        self.splitter.setSizes(kept if len(kept) == self.splitter.count() else sizes)
        self.splitter.setStretchFactor(self.splitter.indexOf(self.table_pane), 1)
        # Side by side, a narrower window takes from both; with the picture on
        # top it was squeezing only the table, down to a sliver.
        self.splitter.setStretchFactor(self.splitter.indexOf(self.video_pane), 1 if side else 0)
        self.side_button.setText("تصویر بالا" if side else "تصویر کنار")
        self.side_button.set_icon("rows" if side else "columns")

    def toggle_video_side(self) -> None:
        self.video_side_chosen = True
        self._arrange_video(side=not self.video_side)

    # -------------------------------------------------------------- ui state

    def _ui_state_path(self) -> Path:
        """Beside the program with the rest of the data, never in AppData."""
        from ..engine.locate import data_dir

        return data_dir() / "ui_state.json"

    def _restore_ui_state(self) -> None:
        try:
            state = json.loads(self._ui_state_path().read_text("utf-8"))
            width, height = int(state["width"]), int(state["height"])
            if width > 400 and height > 300:
                self.resize(width, height)
            if "video_side" in state and self.video is not None:
                self.video_side_chosen = True  # the auto guess must not undo it
                self._arrange_video(side=bool(state["video_side"]))
            key = "splitter_side" if self.video_side else "splitter_top"
            sizes = [int(s) for s in state.get(key, [])]
            if sizes and len(sizes) == self.splitter.count():
                self.splitter.setSizes(sizes)
            self._saved_state = state
        except Exception as error:  # noqa: BLE001 - a bad file must not block editing
            log.debug("وضعیت پنجره خوانده نشد: %s", error)

    def _save_ui_state(self) -> None:
        try:
            # Whatever was read at startup is carried over, so the sizes of the
            # placement not in use right now survive.
            state = dict(self._saved_state)
            state.update(width=self.width(), height=self.height())
            # Sizes are kept per placement: the split of a side-by-side window
            # means nothing once the picture goes back on top.
            state["splitter_side" if self.video_side else "splitter_top"] = self.splitter.sizes()
            # Only a placement the user asked for is kept: otherwise the guess
            # made for a portrait video would stick to the next landscape one.
            if self.video_side_chosen:
                state["video_side"] = self.video_side
            atomic_write_text(self._ui_state_path(), json.dumps(state))
        except Exception as error:  # noqa: BLE001 - saving a preference is not worth a crash
            log.debug("وضعیت پنجره ذخیره نشد: %s", error)

    def _save_project(self) -> None:
        """Write the lines back so the next open starts where this one ended.

        Until now the editor wrote an SRT and nothing else: close the window
        and every split, merge and correction was gone, because only the
        transcription ever saved the project.
        """
        from ..engine.locate import project_path

        if self.shaped:
            index = {id(word): position for position, word in enumerate(self.project.words)}
            lines = []
            for cue in self.cues:
                positions = [index[id(w)] for w in cue.words if id(w) in index]
                if positions:
                    lines.append(EditedLine(words=positions, text=cue.text, edited=cue.edited))
            # An empty list is written too: it means "this subtitle has no
            # lines any more". Returning early instead left the previous ones
            # in the file, so deleting every line brought them all back.
            self.project.lines = lines
        elif self.project.lines:
            self.project.lines = []  # hand lines given up for a style
        elif not self.words_touched:
            return  # nothing shaped by hand; the style still decides the lines
        try:
            target = project_path(self.project.video_path)
            self.project.save(target)
            log.info("ویرایش‌ها ذخیره شد: %s (%d خط)", target, len(self.project.lines))
        except OSError as error:  # noqa: BLE001 - losing a preference beats a crash
            log.warning("ذخیره ویرایش‌ها ممکن نشد: %s", error)

    def _finish(self) -> None:
        """Save the work and let the decoder go -- once, however we got here.

        A dialog that was never shown closes without ever reaching `done()`,
        so both exits call this and the flag keeps it to a single write.
        """
        if self._finished:
            return
        self._finished = True
        self._stop_threads()
        self._save_project()
        self._save_ui_state()
        if self.player is not None:
            # Dropping the source as well frees the decoder: the editor is
            # often closed to start another transcription on the same GPU.
            self.player.stop()
            self.player.setSource(QUrl())

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._finish()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._finish()
        super().done(result)

    # ---------------------------------------------------------- cell editing

    def editor_opened(self, editor: QLineEdit) -> None:
        self.active_editor = editor
        for action in self.editing_shortcuts:
            action.setEnabled(False)

    def editor_closed(self, *_args) -> None:
        """The editor is about to be destroyed; nothing may point at it."""
        self.active_editor = None
        for action in self.editing_shortcuts:
            action.setEnabled(True)

    # ----------------------------------------------------------------- table

    def _fill_row(self, row: int, keep_text_item: bool = False) -> None:
        """Write one cue into its five cells. Signals are the caller's problem.

        `keep_text_item` leaves the text cell alone: right after an edit the
        cell already holds what the user typed, and its editor may still be
        open on it.
        """
        cue = self.cues[row]
        values = [
            timecode(cue.start),
            timecode(cue.end),
            f"{cue.duration:.1f}",
            f"{cue.cps:.0f}",
            cue.text,
        ]
        for column, value in enumerate(values):
            if column == COL_TEXT and keep_text_item and self.table.item(row, COL_TEXT):
                continue
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

    def _refresh_row(self, row: int, keep_text_item: bool = False) -> None:
        """Redraw a single line.

        Rebuilding the whole table on every keystroke made a long subtitle
        stutter, threw the scroll position away, and moved the current cell --
        which then dragged the video off to another line.
        """
        if row < 0 or row >= len(self.cues):
            return
        self.table.blockSignals(True)
        self._fill_row(row, keep_text_item=keep_text_item)
        self.table.blockSignals(False)
        if row < len(self._cue_starts):
            self._cue_starts[row] = self.cues[row].start
        self._update_summary()

    def _update_summary(self) -> None:
        threshold = self.config.low_confidence
        total_words = sum(len(c.words) for c in self.cues)
        shaky = sum(
            1 for c in self.cues for w in c.words if w.probability < threshold
        )
        row = self.table.currentRow() if hasattr(self, "table") else -1
        where = f"خط {row + 1} از {len(self.cues)}" if row >= 0 else f"{len(self.cues)} خط"
        self.position_chip.setText(to_persian_digits(where))
        # One chip that is both the count and the way to the next one.
        if shaky:
            self.suspect_button.setText(to_persian_digits(f"{shaky} کلمه مشکوک"))
            self.suspect_button.set_role("ChipWarn")
            self.suspect_button.set_icon("alert")
        else:
            self.suspect_button.setText("همه کلمه‌ها مطمئن")
            self.suspect_button.set_role("ChipOk")
            self.suspect_button.set_icon("check")
        self.suspect_button.setToolTip(
            to_persian_digits(f"مدل به {shaky} کلمه از {total_words} مطمئن نبود.")
            + "\nبرو سراغ خط مشکوک بعدی — F3"
        )

    def _reload(self, keep_row: int | None = None) -> None:
        scroll = self.table.verticalScrollBar().value()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.cues))
        for row in range(len(self.cues)):
            self._fill_row(row)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)

        self._cue_starts = [c.start for c in self.cues]
        self._update_wave()
        self._update_summary()
        if keep_row is not None and self.table.rowCount():
            row = max(0, min(keep_row, self.table.rowCount() - 1))
            self.table.setCurrentCell(row, COL_TEXT)
        else:
            self.table.verticalScrollBar().setValue(scroll)

    def _rebalance_pair(self, first: int) -> bool:
        """After a hand edit, re-split the words at the new line break.

        Only when the two lines together still say the same thing: then the
        user moved a word across the boundary and the timings must follow. If
        a word was actually corrected the sequences differ and nothing moves,
        so retyping a word never disturbs the timeline.
        """
        second = first + 1
        if not (0 <= first and second < len(self.cues)):
            return False
        left, right = self.cues[first], self.cues[second]
        typed = left.text.split() + right.text.split()
        words = left.words + right.words
        if len(typed) != len(words):
            return False
        if [bare_word(t) for t in typed] != [bare_word(w.text) for w in words]:
            return False

        cut = len(left.text.split())
        if cut == len(left.words):
            return False  # the break is already where the text says it is
        if cut == 0 or cut == len(words):
            return False  # that would empty a line; merging is the right tool

        left.words, right.words = words[:cut], words[cut:]
        return True

    def _current_row(self) -> int:
        row = self.table.currentRow()
        return row if row >= 0 else 0

    def _text_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != COL_TEXT:
            return
        # Read once: `_reload` below replaces every item, and asking the old
        # one for its row afterwards raised "C++ object already deleted".
        row = item.row()
        cue = self.cues[row]
        if cue.text != item.text().strip():
            self._snapshot()
        cue.text = item.text().strip()
        cue.edited = True
        self.last_edited_row = row
        moved = self._rebalance_pair(row - 1) | self._rebalance_pair(row)
        if moved:
            # A word changed cue, so both spans moved: the whole table has to
            # be redrawn, not just this row.
            self._reload(keep_row=row)
            self._set_overlay_text(self.cues[row].text)
            return
        # The edit arrives while the cell editor is still open on this item:
        # replacing it here would pull the ground out from under the editor.
        self._refresh_row(row, keep_text_item=True)
        if row == self.table.currentRow():
            self._set_overlay_text(cue.text)

    # -------------------------------------------------------------- playback

    def play_selected(self) -> None:
        """Play the current line, and stop where it ends."""
        from PySide6.QtMultimedia import QMediaPlayer

        row = self._current_row()
        if self.player is None or row >= len(self.cues):
            return
        # A nudge counts as paused: pressing Space right after picking a line
        # should play it, not stop the frame that is being shown.
        if self.player.playbackState() == QMediaPlayer.PlayingState and not self.nudging:
            self.player.pause()
            return
        cue = self.cues[row]
        self.stop_at = 0.0 if self.continuous_box.isChecked() else cue.end + 0.15
        self._seek(cue.start - 0.1, play=True)

    def _seek(self, seconds: float, play: bool = False) -> None:
        """The one way the picture ever moves.

        Before the media reports LoadedMedia a seek is dropped on the floor,
        which is why selecting a line right after the editor opened used to do
        nothing at all. The request waits here instead.
        """
        if self.player is None:
            return
        if not self.media_ready:
            self.pending_seek = seconds
            self.pending_play = self.pending_play or play
            return
        self.player.setPosition(int(max(0.0, seconds) * 1000))
        if play:
            # A nudge started a moment ago would pause this playback again as
            # soon as its timer fires, so it is called off here.
            self.nudging = False
            self.audio_out.setMuted(False)
            self.player.play()
            self._sync_play_button()
        else:
            self._show_frame()

    def _show_frame(self) -> None:
        """Seeking while paused leaves the old frame up, so play a moment."""
        if self.player is None or self.nudging:
            return
        self.nudging = True
        self.stop_at = 0.0  # the nudge must not trip the stop-at-cue-end check
        self.audio_out.setMuted(True)
        self.player.play()
        QTimer.singleShot(NUDGE_TIMEOUT_MS, self, self._end_nudge)

    def _frame_arrived(self, _frame) -> None:
        """One frame is enough: the picture now shows the chosen line."""
        if self.nudging:
            self._end_nudge()

    def _end_nudge(self) -> None:
        if not self.nudging:
            return  # a real play took over in the meantime
        if self.player is not None:
            self.player.pause()
            self.audio_out.setMuted(False)
        self.nudging = False
        self._sync_play_button()

    def _row_selected(self, row: int, column: int, *_rest) -> None:
        """Park the video on the selected line without starting playback."""
        from PySide6.QtMultimedia import QMediaPlayer

        if row < 0 or row >= len(self.cues):
            return
        self._set_overlay_text(self.cues[row].text)
        self._update_summary()
        self._update_wave(row)
        if self.player is None:
            return
        if self.following:
            return  # the video is driving the table, not the other way round
        playing = self.player.playbackState() == QMediaPlayer.PlayingState and not self.nudging
        if row == self.last_seek_row and not playing:
            return  # a redraw is not a new line
        self.last_seek_row = row
        cue = self.cues[row]
        if playing:
            # Picking a line while it runs means "play from there".
            self.stop_at = 0.0 if self.continuous_box.isChecked() else cue.end + 0.15
            self._seek(cue.start, play=True)
        else:
            self._seek(cue.start)

    def _position_changed(self, position_ms: int) -> None:
        self._stop_at_cue_end(position_ms)
        seconds = position_ms / 1000.0
        if self.wave is not None:
            self.wave.set_playhead(seconds)
        if self.slider is not None and not self.slider.isSliderDown():
            self.slider.setValue(position_ms)
            self.clock.setText(f"{timecode(seconds)} / {timecode(self.slider.maximum() / 1000.0)}")
        if self.player is not None and not self.nudging:
            from PySide6.QtMultimedia import QMediaPlayer

            if self.player.playbackState() == QMediaPlayer.PlayingState:
                row = cue_index_at(self.cues, self._cue_starts, seconds)
                self._set_overlay_text(self.cues[row].text if row >= 0 else "")
                self._follow_playhead(row)

    def _follow_playhead(self, row: int) -> None:
        """Keep the line being spoken selected and in view while it plays.

        Without this the reader has to scroll by hand to find where the video
        got to, which is most of the work in a long subtitle.
        """
        if row < 0 or row == self.table.currentRow():
            return
        self.following = True
        try:
            self.table.setCurrentCell(row, COL_TEXT)
            self.table.scrollToItem(self.table.item(row, COL_TEXT), QAbstractItemView.PositionAtCenter)
            self.last_seek_row = row
        finally:
            self.following = False
        self._update_summary()

    def _duration_changed(self, duration_ms: int) -> None:
        if self.slider is not None:
            self.slider.setRange(0, max(0, duration_ms))
            self.clock.setText(f"{timecode(0)} / {timecode(duration_ms / 1000.0)}")

    def _slider_moved(self, position_ms: int) -> None:
        self.stop_at = 0.0
        self._seek(position_ms / 1000.0)

    def _playback_state_changed(self, _state) -> None:
        self._sync_play_button()

    def _sync_play_button(self) -> None:
        """The muted nudge is playback to Qt, but not to the reader."""
        from PySide6.QtMultimedia import QMediaPlayer

        if self.player is None or getattr(self, "play_button", None) is None:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlayingState and not self.nudging
        self.play_button.setText(PAUSE_LABEL if playing else PLAY_LABEL)
        self.play_button.set_icon("pause" if playing else "play")

    def _set_overlay_text(self, text: str) -> None:
        if self.video is None:
            return
        self.video.set_caption(text)

    def _stop_at_cue_end(self, position_ms: int) -> None:
        if self.player is not None and self.stop_at and position_ms >= self.stop_at * 1000:
            self.player.pause()
            self.stop_at = 0.0

    # --------------------------------------------------------------- history

    def _copy_cues(self) -> list[EditableCue]:
        """A snapshot that shares the words instead of copying them.

        Nothing in the editor ever mutates a Word -- only `text` and `edited`
        on the cue change -- so a deep copy of the whole stream on every
        keystroke was paid for nothing, and it showed on a long subtitle.
        """
        return [replace(cue, words=list(cue.words)) for cue in self.cues]

    def _snapshot(self, times: list[Word] | None = None) -> None:
        """Remember the lines before a change.

        Snapshots share the Word objects, so a change to a word's own time (an
        edge dragged on the waveform) passes those words in `times`, and their
        start and end are kept beside the snapshot.
        """
        self.shaped = True
        self.history.append(self._copy_cues())
        self._times_history.append([(w, w.start, w.end) for w in times or []])
        del self.history[:-50]  # a long session should not grow without bound
        del self._times_history[:-50]
        self.redo_stack.clear()
        self._times_redo.clear()
        self._update_history_buttons()

    @staticmethod
    def _swap_times(saved: list) -> list:
        """Put saved word times back; return the ones they replaced."""
        current = [(w, w.start, w.end) for w, _, _ in saved]
        for word, start, end in saved:
            word.start, word.end = start, end
        return current

    def undo(self) -> None:
        if not self.history:
            return
        times = self._times_history.pop() if self._times_history else []
        self._times_redo.append(self._swap_times(times))
        self.redo_stack.append(self._copy_cues())
        self.cues = self.history.pop()
        self._reload()
        self._update_history_buttons()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        times = self._times_redo.pop() if self._times_redo else []
        self._times_history.append(self._swap_times(times))
        self.history.append(self._copy_cues())
        self.cues = self.redo_stack.pop()
        self._reload()
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self.history))
        self.redo_button.setEnabled(bool(self.redo_stack))

    # ------------------------------------------------------------ operations

    def _caret_token(self) -> int | None:
        """Which word the caret sits after, while a cell is being edited.

        This is what makes the break point the user's decision instead of the
        program's: put the cursor where the line should end, press the split
        shortcut, and the cut happens there.
        """
        editor = self.active_editor
        if editor is None:
            return None
        typed = editor.text()
        caret = editor.cursorPosition()
        # A caret inside a word keeps that word on the first line: the reader
        # is pointing at the gap after it, not at the letter.
        return len(typed[:caret].split())

    def split_selected(self) -> None:
        """Cut one line into two, each keeping the timing of its own words.

        With the caret in the text the cut lands exactly there. Without it the
        line is halved, which is what the button did before.
        """
        row = self._current_row()
        if row >= len(self.cues):
            return
        at_token = self._caret_token()
        if self.active_editor is not None:
            # Commit what is being typed before the line is taken apart.
            self.table.setFocus()

        cue = self.cues[row]
        if len(cue.words) < 2:
            QMessageBox.information(self, "تقسیم", "این خط فقط یک کلمه دارد")
            return

        tokens = cue.text.split()
        if at_token is None:
            cut = len(cue.words) // 2
        elif len(tokens) == len(cue.words):
            cut = at_token
        else:
            # The text was retyped, so the words no longer line up with it one
            # for one; the best available guess is the same share of the line.
            share = at_token / max(len(tokens), 1)
            cut = round(share * len(cue.words))
        cut = max(1, min(cut, len(cue.words) - 1))

        first = EditableCue(words=cue.words[:cut])
        second = EditableCue(words=cue.words[cut:])
        if at_token is not None and 0 < at_token < len(tokens):
            # The caret says exactly where the text breaks.
            first.text = " ".join(tokens[:at_token])
            second.text = " ".join(tokens[at_token:])
        else:
            first.text, second.text = split_text(cue.text, cut, len(cue.words))
        # Each half keeps its share of the baseline, so a correction made
        # before the split can still be taught afterwards.
        if cue.original and cue.original != cue.text:
            first.original, second.original = split_text(cue.original, cut, len(cue.words))
        else:
            first.original, second.original = first.text, second.text
        for half in (first, second):
            if not half.text:  # nothing of the shown text fell on this side
                half.text = half.original = " ".join(w.text for w in half.words)
        first.edited = second.edited = cue.edited

        self._snapshot()
        self.cues[row : row + 1] = [first, second]
        self._reload(keep_row=row)

    def selected_rows(self) -> list[int]:
        """Every row the user has highlighted, in order.

        Falls back to the current row: with nothing dragged over, the buttons
        still act on the line under the cursor.
        """
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        rows = [row for row in rows if 0 <= row < len(self.cues)]
        return rows or [self._current_row()]

    def merge_selected(self) -> None:
        """Join the selected lines into one; the times simply span them all.

        Selecting three lines and pressing merge used to fold only the first
        into the second, which read as "merge does not work".
        """
        rows = self.selected_rows()
        if len(rows) < 2:
            # A single line means "join me with the next one".
            row = rows[0]
            if row + 1 >= len(self.cues):
                return
            rows = [row, row + 1]
        if rows != list(range(rows[0], rows[-1] + 1)):
            QMessageBox.information(
                self, "ادغام", "خط‌های انتخاب‌شده باید پشت سر هم باشند."
            )
            return

        self._snapshot()
        first, last = rows[0], rows[-1]
        block = self.cues[first : last + 1]
        merged = EditableCue(words=[w for cue in block for w in cue.words])
        merged.text = " ".join(cue.text for cue in block if cue.text).strip()
        merged.original = " ".join(cue.original for cue in block if cue.original).strip()
        merged.edited = any(cue.edited for cue in block)
        self.cues[first : last + 1] = [merged]
        self._reload(keep_row=first)

    def move_word_down(self) -> None:
        """Push the last word of this line onto the front of the next one."""
        self._move_word(down=True)

    def move_word_up(self) -> None:
        """Pull the first word of this line onto the end of the one above."""
        self._move_word(down=False)

    def _move_word(self, down: bool) -> None:
        """Move the word and its timing together.

        Retyping the two lines by hand moves only the letters: the word object
        stays where it was, so the line keeps its old end and the word is read
        out of time. Here the word itself changes cue, and both spans are
        recomputed from the words they now hold.
        """
        row = self._current_row()
        other = row + 1 if down else row - 1
        if not (0 <= row < len(self.cues)) or not (0 <= other < len(self.cues)):
            return
        source, target = self.cues[row], self.cues[other]
        if len(source.words) < 2:
            QMessageBox.information(
                self, "انتقال کلمه", "این خط فقط یک کلمه دارد؛ به‌جایش ادغام کن."
            )
            return

        self._snapshot()
        if down:
            word = source.words.pop()
            target.words.insert(0, word)
        else:
            word = source.words.pop(0)
            target.words.append(word)

        # The word's text travels with it, as shown on screen. Rebuilding both
        # lines from the raw model words threw away every correction on them.
        for attribute in ("text", "original"):
            moved = _move_token(getattr(source, attribute), getattr(target, attribute), down)
            if moved is None:
                for cue in (source, target):
                    setattr(cue, attribute, " ".join(w.text for w in cue.words))
            else:
                setattr(source, attribute, moved[0])
                setattr(target, attribute, moved[1])
        self._reload(keep_row=row)

    def delete_selected(self) -> None:
        """Remove every selected line, not just the one under the cursor."""
        rows = self.selected_rows()
        if not rows:
            return
        self._snapshot()
        for row in reversed(rows):
            if row < len(self.cues):
                del self.cues[row]
        self._reload(keep_row=rows[0])

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

        try:
            for heard_word, correct_word in pairs:
                path = add_correction(heard_word, correct_word)
        except OSError as error:
            log.exception("دیکشنری ذخیره نشد")
            QMessageBox.warning(
                self,
                "دیکشنری",
                f"ذخیره در دیکشنری ممکن نشد:\n{error}\n\n"
                "اگر فایل دیکشنری جای دیگری باز است ببندش و دوباره بزن.",
            )
            return

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

    # ---------------------------------------------------------- live style

    def _style_changed(self, index: int) -> None:
        """Rebuild the lines in another style, on the spot."""
        from dataclasses import replace

        name = self.style_box.itemData(index)
        if name in BUILTIN_PROFILES:
            profile = replace(BUILTIN_PROFILES[name])
        elif self.config.custom_profile is not None and name == self.config.custom_profile.name:
            profile = replace(self.config.custom_profile)
        else:
            return
        if self.shaped:
            answer = QMessageBox.question(
                self,
                "تغییر سبک",
                "خط‌های این زیرنویس را دستی شکل داده‌ای. با سبک تازه، تقسیم و ادغام‌ها و "
                "متن‌های اصلاح‌شده کنار گذاشته می‌شوند (اصلاح‌های دیکشنری می‌مانند).\n\nادامه بدهم؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.style_box.blockSignals(True)
                self.style_box.setCurrentIndex(max(0, self.style_box.findData(self.config.profile.name)))
                self.style_box.blockSignals(False)
                return
        self.config.profile = profile
        self.cues = cues_to_editable(
            self.project, build_cues(self.project.words, profile, self.config.text)
        )
        # The new lines are the style's, not the user's; the hand-made ones
        # cannot come back through undo, which the question above said.
        self.shaped = False
        self.history.clear()
        self.redo_stack.clear()
        self._times_history.clear()
        self._times_redo.clear()
        self._update_history_buttons()
        self.last_seek_row = -1
        self._reload(keep_row=0)

    # ------------------------------------------------------------- waveform

    def _start_waveform(self, media: Path) -> None:
        if self.wave is None:
            return
        worker = EnvelopeWorker(media)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.ready.connect(self.wave.set_envelope, Qt.QueuedConnection)
        worker.failed.connect(self.wave.set_failed, Qt.QueuedConnection)
        worker.ready.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self._wave_worker = worker  # kept alive until the thread ends
        self.wave_thread = thread
        thread.start()

    def _update_wave(self, row: int | None = None) -> None:
        if self.wave is None:
            return
        current = self.table.currentRow() if row is None else row
        self.wave.set_lines([(c.start, c.end) for c in self.cues], current)

    def _edge_moved(self, which: str, seconds: float) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.cues)):
            return
        cue = self.cues[row]
        self._snapshot(times=[cue.words[0], cue.words[-1]])
        move_edge(self.cues, row, which, seconds)
        self.words_touched = True
        self._refresh_row(row)
        self._update_wave(row)

    def _stop_threads(self) -> None:
        """No thread may outlive the dialog: Qt kills the process for it."""
        if self.wave_thread is not None:
            self._wave_worker.cancel()
            self.wave_thread.quit()
            self.wave_thread.wait(10_000)
        if self.burn_thread is not None:
            self._burn_worker.cancel()
            self.burn_thread.quit()
            self.burn_thread.wait(30_000)

    def _wave_seek(self, seconds: float) -> None:
        self.stop_at = 0.0
        self._seek(seconds)

    # ------------------------------------------------------------- keywords

    def keyword_texts(self, cue: "EditableCue") -> set[str]:
        """Bare texts of the keywords in a line, when the style shows keywords."""
        profile = self.config.profile
        if not (profile.keyword_solo or profile.mode == "word"):
            return set()
        return {w.text.strip("،؛:.!؟…") for w in cue.words if w.keyword}

    def _context_menu(self, position) -> None:
        row = self.table.rowAt(position.y())
        if not (0 <= row < len(self.cues)):
            return
        menu = QMenu(self)
        keywords = menu.addMenu("کلمه کلیدی (سبک ریلز و کلمه به کلمه)")
        for word in self.cues[row].words:
            action = keywords.addAction(word.text)
            action.setCheckable(True)
            action.setChecked(bool(word.keyword))
            action.toggled.connect(lambda on, w=word: self.set_keyword(w, on))
        menu.addSeparator()
        menu.addAction("جستجو و جایگزینی… (Ctrl+H)", self.find_replace)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def set_keyword(self, word: Word, on: bool) -> None:
        """The user's own choice; the detector never overrides it."""
        word.keyword = on
        word.edited = True
        self.words_touched = True
        self._reload(keep_row=self.table.currentRow())

    # ---------------------------------------------------------- find/replace

    def find_replace(self) -> None:
        FindReplaceDialog(self.replace_everywhere, self).exec()

    def replace_everywhere(self, find: str, replacement: str, whole: bool, teach: bool) -> int:
        # Counted first: a search that finds nothing must not leave a
        # snapshot behind, which would mark the lines as shaped by hand.
        if not any(replace_in_text(c.text, find, replacement, whole)[1] for c in self.cues):
            return 0
        self._snapshot()
        count = replace_in_cues(self.cues, find, replacement, whole)
        if teach and " " not in find:
            try:
                add_correction(find, replacement)
            except OSError as error:
                QMessageBox.warning(self, "دیکشنری", f"ذخیره در دیکشنری ممکن نشد:\n{error}")
        self._reload(keep_row=self.table.currentRow())
        return count

    # ----------------------------------------------------------------- burn

    def burn_video(self) -> None:
        """Draw the subtitle into a copy of the video, on its own thread."""
        from ..pipeline import output_path
        from ..render.burn import burned_path

        if self.burn_thread is not None:
            return
        cues = self.to_cues()
        if not cues:
            QMessageBox.warning(self, "ویدیو با زیرنویس", "خط قابل نمایشی نمانده است.")
            return
        video = Path(self.project.video_path)
        target = burned_path(output_path(video, self.config, ".srt"))
        if self.player is not None:
            self.player.pause()

        progress = QProgressDialog("در حال ساخت ویدیو با زیرنویس…", "لغو", 0, 100, self)
        progress.setWindowTitle("ویدیو با زیرنویس")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        worker = BurnWorker(video, cues, self.config.ass_style, target)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(progress.setValue, Qt.QueuedConnection)
        worker.finished.connect(self._burn_done, Qt.QueuedConnection)
        worker.failed.connect(self._burn_failed, Qt.QueuedConnection)
        worker.stopped.connect(self._burn_stopped, Qt.QueuedConnection)
        for signal in (worker.finished, worker.failed, worker.stopped):
            signal.connect(thread.quit)
        thread.finished.connect(self._burn_thread_ended, Qt.QueuedConnection)
        # Through a slot of this dialog, on the GUI thread: connected to the
        # worker itself the request would queue behind the burn it is meant
        # to stop, and never arrive.
        progress.canceled.connect(self._cancel_burn)
        self._burn_worker, self._burn_progress = worker, progress
        self.burn_thread = thread
        self.burn_button.setEnabled(False)
        thread.start()

    def _cancel_burn(self) -> None:
        if self.burn_thread is not None:
            self._burn_worker.cancel()

    def _burn_done(self, path: str) -> None:
        self._burn_progress.reset()
        QMessageBox.information(self, "ویدیو آماده شد", path)

    def _burn_failed(self, message: str) -> None:
        self._burn_progress.reset()
        QMessageBox.warning(self, "ساخت ویدیو انجام نشد", message)

    def _burn_stopped(self) -> None:
        self._burn_progress.reset()

    def _burn_thread_ended(self) -> None:
        if self.burn_thread is not None:
            self.burn_thread.wait(5000)
        self.burn_thread = None
        self.burn_button.setEnabled(True)

    # --------------------------------------------------------------- export

    def to_cues(self) -> list[Cue]:
        """The lines as cues, timed by the same rules as a rendered style.

        Writing the raw word times out left one-word lines on screen for a
        fifth of a second, and a subtitle exported from here timed
        differently from the very same lines rendered by the pipeline.
        """
        return cues_from_lines([(cue.words, cue.text) for cue in self.cues], self.config.profile)

    def export(self) -> None:
        from ..pipeline import output_path
        from pathlib import Path

        from ..pipeline import video_frame
        from ..render.writers import DEFAULT_FRAME

        cues = self.to_cues()
        if not cues:
            QMessageBox.warning(self, "ذخیره زیرنویس", "خط قابل ذخیره‌ای نمانده است.")
            return

        suffix = self.config.suffix
        target = output_path(Path(self.project.video_path), self.config, suffix)
        try:
            write_subtitle(
                cues,
                target,
                bom=self.config.text.bom,
                style=self.config.ass_style,
                frame=video_frame(self.project.video_path) if suffix == ".ass" else DEFAULT_FRAME,
            )
        except OSError as error:
            # A read-only folder, or the file still open in another program.
            log.exception("نوشتن زیرنویس شکست خورد: %s", target)
            QMessageBox.critical(
                self,
                "ذخیره نشد",
                f"نوشتن این فایل ممکن نشد:\n{target}\n\n{error}\n\n"
                "اگر فایل جای دیگری باز است ببندش و دوباره بزن.",
            )
            return
        self._save_project()
        QMessageBox.information(self, "ذخیره شد", str(target))
        self.accept()
