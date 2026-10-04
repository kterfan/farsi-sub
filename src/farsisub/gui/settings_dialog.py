"""Advanced settings: a style of one's own, keyword sensitivity, subtitle look.

Everything here already existed as fields on the config; this is the first
place a user can reach them without editing JSON.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QAbstractSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import BUILTIN_PROFILES, CUSTOM_PROFILE, AppConfig, AssStyle, StyleProfile
from . import theme

MODE_LABELS = {
    "sentence": "جمله‌ای",
    "smart": "هوشمند",
    "reels": "ریلز",
    "word": "کلمه به کلمه",
}


class ColorButton(QPushButton):
    """A swatch that opens a colour picker."""

    def __init__(self, color: str) -> None:
        super().__init__()
        self.setFixedWidth(110)
        self.setLayoutDirection(Qt.LeftToRight)  # "#FFFFFF", not "FFFFFF#"
        self.set_color(color)
        self.clicked.connect(self._pick)

    def set_color(self, color: str) -> None:
        valid = QColor(color)
        self.color = valid.name().upper() if valid.isValid() else "#FFFFFF"
        self.setText(self.color)
        self.setStyleSheet(
            f"background-color:{self.color};"
            f"color:{'#000000' if QColor(self.color).lightness() > 128 else '#FFFFFF'};"
        )

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.color), self, "انتخاب رنگ")
        if chosen.isValid():
            self.set_color(chosen.name())


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("تنظیمات پیشرفته")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(900, 560)
        # Group boxes are styled by the shared sheet, title above the card.

        base = config.custom_profile or replace(
            config.profile, name=CUSTOM_PROFILE, label="سبک من"
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE * 2)
        columns = QHBoxLayout()
        columns.setSpacing(theme.SPACE * 3)
        first, second = QVBoxLayout(), QVBoxLayout()
        first.addWidget(self._style_group(base))
        first.addWidget(self._keyword_group())
        first.addStretch(1)
        second.addWidget(self._look_group(config.ass_style))
        second.addWidget(self._output_group())
        second.addStretch(1)
        columns.addLayout(first, stretch=1)
        columns.addLayout(second, stretch=1)
        layout.addLayout(columns, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("ذخیره")
        buttons.button(QDialogButtonBox.Save).setObjectName("Primary")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------------------------------------------------------------- groups

    def _style_group(self, base: StyleProfile) -> QGroupBox:
        box = QGroupBox("سبک شخصی")
        form = QFormLayout(box)
        self.label_edit = QLineEdit(base.label)
        self.mode_box = QComboBox()
        for mode, label in MODE_LABELS.items():
            self.mode_box.addItem(label, mode)
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(base.mode)))
        self.mode_box.setToolTip("روش برش: سبک شخصی روی کدام سبک ساخته شود")

        self.lines_spin = _spin(1, 3, base.max_lines)
        self.chars_spin = _spin(10, 80, base.max_chars_per_line)
        self.min_spin = _dspin(0.1, 5.0, base.min_duration, 0.1, " ثانیه")
        self.max_spin = _dspin(0.5, 15.0, base.max_duration, 0.5, " ثانیه")
        self.cps_spin = _dspin(5.0, 60.0, base.max_cps, 1.0, " حرف در ثانیه")
        self.gap_spin = _dspin(0.0, 1.0, base.min_gap, 0.02, " ثانیه")

        form.addRow("نام", self.label_edit)
        form.addRow("روش برش", self.mode_box)
        form.addRow("حداکثر سطر", self.lines_spin)
        form.addRow("حداکثر حرف در هر سطر", self.chars_spin)
        form.addRow("کمترین زمان نمایش", self.min_spin)
        form.addRow("بیشترین زمان نمایش", self.max_spin)
        form.addRow("سرعت خواندن", self.cps_spin)
        form.addRow("فاصله بین خط‌ها", self.gap_spin)
        self.use_custom_box = QCheckBox("بعد از ذخیره، همین سبک انتخاب شود")
        self.use_custom_box.setChecked(True)
        form.addRow(self.use_custom_box)
        return box

    def _keyword_group(self) -> QGroupBox:
        box = QGroupBox("کلمه کلیدی (سبک ریلز)")
        row = QHBoxLayout(box)
        self.sensitivity = QSlider(Qt.Horizontal)
        self.sensitivity.setRange(0, 100)
        self.sensitivity.setValue(round(self.config.keywords.sensitivity * 100))
        self.sensitivity_label = QLabel()
        self.sensitivity.valueChanged.connect(self._show_sensitivity)
        self._show_sensitivity(self.sensitivity.value())
        row.addWidget(QLabel("کمتر"))
        row.addWidget(self.sensitivity, stretch=1)
        row.addWidget(QLabel("بیشتر"))
        row.addWidget(self.sensitivity_label)
        return box

    def _show_sensitivity(self, value: int) -> None:
        share = 0.02 + 0.10 * value / 100
        self.sensitivity_label.setText(f"حدود {share * 100:.0f}٪ کلمه‌ها")

    def _look_group(self, style: AssStyle) -> QGroupBox:
        box = QGroupBox("ظاهر زیرنویس (خروجی ASS و ویدیوی زیرنویس‌دار)")
        form = QFormLayout(box)
        self.font_edit = QLineEdit(style.font)
        self.size_spin = _spin(20, 200, style.size)
        self.color_button = ColorButton(style.color)
        self.keyword_color_button = ColorButton(style.keyword_color)
        self.outline_color_button = ColorButton(style.outline_color)
        self.outline_spin = _dspin(0.0, 10.0, style.outline, 0.5, "")
        self.margin_spin = _spin(0, 500, style.margin_bottom)
        self.bold_box = QCheckBox("ضخیم")
        self.bold_box.setChecked(style.bold)
        form.addRow("فونت", self.font_edit)
        form.addRow("اندازه (برای تصویر ۱۰۸۰)", self.size_spin)
        form.addRow("رنگ متن", self.color_button)
        form.addRow("رنگ کلمه کلیدی", self.keyword_color_button)
        form.addRow("رنگ حاشیه", self.outline_color_button)
        form.addRow("ضخامت حاشیه", self.outline_spin)
        form.addRow("فاصله از پایین", self.margin_spin)
        form.addRow(self.bold_box)
        reset = QPushButton("بازگشت به پیش‌فرض ظاهر")
        reset.clicked.connect(lambda: self._show_look(AssStyle()))
        form.addRow(reset)
        return box

    def _show_look(self, style: AssStyle) -> None:
        self.font_edit.setText(style.font)
        self.size_spin.setValue(style.size)
        self.color_button.set_color(style.color)
        self.keyword_color_button.set_color(style.keyword_color)
        self.outline_color_button.set_color(style.outline_color)
        self.outline_spin.setValue(style.outline)
        self.margin_spin.setValue(style.margin_bottom)
        self.bold_box.setChecked(style.bold)

    def _output_group(self) -> QGroupBox:
        box = QGroupBox("پوشه خروجی")
        row = QHBoxLayout(box)
        self.output_edit = QLineEdit(self.config.output_dir or "")
        self.output_edit.setPlaceholderText("کنار خود ویدیو")
        self.output_edit.setLayoutDirection(Qt.LeftToRight)
        browse = QPushButton("انتخاب…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.output_edit, stretch=1)
        row.addWidget(browse)
        return box

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "پوشه خروجی", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    # ----------------------------------------------------------------- apply

    def profile(self) -> StyleProfile:
        mode = self.mode_box.currentData()
        start = replace(BUILTIN_PROFILES[mode]) if mode in BUILTIN_PROFILES else replace(
            BUILTIN_PROFILES["smart"]
        )
        min_duration = self.min_spin.value()
        return replace(
            start,
            name=CUSTOM_PROFILE,
            label=self.label_edit.text().strip() or "سبک من",
            mode=mode,
            max_lines=self.lines_spin.value(),
            max_chars_per_line=self.chars_spin.value(),
            min_duration=min_duration,
            max_duration=max(min_duration, self.max_spin.value()),
            max_cps=self.cps_spin.value(),
            min_gap=self.gap_spin.value(),
        )

    def look(self) -> AssStyle:
        return AssStyle(
            font=self.font_edit.text().strip() or AssStyle.font,
            size=self.size_spin.value(),
            color=self.color_button.color,
            keyword_color=self.keyword_color_button.color,
            outline=self.outline_spin.value(),
            outline_color=self.outline_color_button.color,
            margin_bottom=self.margin_spin.value(),
            bold=self.bold_box.isChecked(),
        )

    def apply_to(self, config: AppConfig) -> None:
        profile = self.profile()
        config.custom_profile = profile
        # The style in use is updated too when it is this one, checked or
        # not: otherwise the new numbers waited for the next start.
        if self.use_custom_box.isChecked() or config.profile.name == CUSTOM_PROFILE:
            config.profile = replace(profile)
        config.keywords.sensitivity = self.sensitivity.value() / 100
        config.ass_style = self.look()
        config.output_dir = self.output_edit.text().strip() or None

    def accept(self) -> None:
        self.apply_to(self.config)
        super().accept()


def _spin(low: int, high: int, value: int) -> QSpinBox:
    spin = QSpinBox()
    # Typing or the mouse wheel; the stylesheet leaves no room for arrows.
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setRange(low, high)
    spin.setValue(int(min(high, max(low, value))))
    return spin


def _dspin(low: float, high: float, value: float, step: float, suffix: str) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setRange(low, high)
    spin.setSingleStep(step)
    spin.setDecimals(2)
    spin.setSuffix(suffix)
    spin.setValue(float(min(high, max(low, value))))
    return spin
