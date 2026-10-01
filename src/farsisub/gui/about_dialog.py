"""About FarsiSub: what it is, who made it, where it lives."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import brand
from ..engine import locate
from . import theme


def version_report() -> str:
    """What a bug report needs: the app, the engine, the hardware."""
    import platform

    return "\n".join(
        [
            f"{brand.APP_NAME} {brand.VERSION}",
            f"Engine: whisper.cpp ({'NVIDIA GPU' if locate.has_cuda() else 'CPU'})",
            f"Models: {', '.join(locate.installed_models()) or '-'}",
            f"Windows: {platform.platform()}",
            brand.REPO_URL,
        ]
    )


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"درباره {brand.APP_NAME}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE * 6, theme.SPACE * 6, theme.SPACE * 6, theme.SPACE * 4)
        layout.setSpacing(theme.SPACE * 2)

        logo = QLabel()
        logo.setPixmap(QPixmap.fromImage(brand.logo_image(96)))
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        name = QLabel(f"{brand.APP_NAME} · {brand.APP_NAME_FA}")
        name.setObjectName("Display")
        name.setAlignment(Qt.AlignCenter)
        layout.addWidget(name)

        version = QLabel(f"نسخه {brand.VERSION}")
        version.setObjectName("Muted")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        tagline = QLabel(
            "ساخت زیرنویس فارسی از روی ویدیو، کاملاً روی همین کامپیوتر؛ "
            "بدون اینترنت و بدون فرستادن فایل به جایی."
        )
        tagline.setWordWrap(True)
        tagline.setAlignment(Qt.AlignCenter)
        layout.addWidget(tagline)
        layout.addSpacing(theme.SPACE * 2)

        self.author = QLabel(
            f"طراحی و برنامه‌نویسی<br><b>{brand.AUTHOR_FA}</b><br>"
            f'<span dir="ltr">{brand.AUTHOR_EN}</span>'
        )
        self.author.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.author)

        self.link = QLabel(f'<a href="{brand.REPO_URL}">{brand.REPO_LABEL}</a>')
        self.link.setOpenExternalLinks(True)
        self.link.setAlignment(Qt.AlignCenter)
        self.link.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.link)

        licence = QLabel("مجوز MIT · متن‌باز")
        licence.setObjectName("Muted")
        licence.setAlignment(Qt.AlignCenter)
        layout.addWidget(licence)
        layout.addSpacing(theme.SPACE * 2)

        buttons = QHBoxLayout()
        copy_button = QPushButton("کپی اطلاعات نسخه")
        copy_button.setObjectName("Quiet")
        copy_button.setToolTip("برای گزارش مشکل: نسخه برنامه، موتور و سیستم")
        copy_button.clicked.connect(self._copy)
        self.copied = QLabel("")
        self.copied.setObjectName("Muted")
        close = QPushButton("بستن")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(copy_button)
        buttons.addWidget(self.copied)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(version_report())
        self.copied.setText("کپی شد")
