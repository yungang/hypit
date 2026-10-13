from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap

PALETTE = [("#5b8def", "#8e5bef"), ("#ef5b7f", "#ef9a5b"), ("#2fb59a", "#5bb8ef"),
           ("#ef8a5b", "#efd35b"), ("#6a5bef", "#ef5bd1"), ("#4aa564", "#b5d94a")]


def placeholder_pixmap(width: int, height: int, text: str, key: int = 0) -> QPixmap:
    """A gradient tile with a short label, used where no cover or thumbnail exists."""
    a, b = PALETTE[key % len(PALETTE)]
    pixmap = QPixmap(width, height)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0, QColor(a))
    gradient.setColorAt(1, QColor(b))
    painter.fillRect(0, 0, width, height, gradient)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setPixelSize(max(12, height // 5))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, width, height), Qt.AlignCenter | Qt.TextWordWrap, text)
    painter.end()
    return pixmap


def cover_pixmap(path: str, width: int, height: int, fallback_text: str, key: int = 0) -> QPixmap:
    """Load an image scaled and cropped to fill width x height, else a placeholder."""
    if path and Path(path).is_file():
        image = QPixmap(path)
        if not image.isNull():
            scaled = image.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            return scaled.copy((scaled.width() - width) // 2, (scaled.height() - height) // 2, width, height)
    return placeholder_pixmap(width, height, fallback_text, key)
