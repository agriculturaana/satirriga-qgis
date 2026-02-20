"""Secao expansivel/colapsavel reutilizavel.

Widget com header clicavel (titulo + seta) e area de conteudo
que expande/colapsa com animacao de altura.
"""

from qgis.PyQt.QtCore import Qt, QPropertyAnimation, QEasingCurve
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QToolButton, QFrame, QSizePolicy,
)


class CollapsibleSection(QWidget):
    """Secao com header clicavel que expande/colapsa o conteudo."""

    def __init__(self, title: str, icon: str = "", expanded: bool = True, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self._animation_duration = 150

        # Header: botao clicavel com seta
        self._toggle_btn = QToolButton()
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(expanded)
        self._toggle_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        label = f"{icon} {title}".strip() if icon else title
        self._toggle_btn.setText(f"  {label}")
        self._toggle_btn.setArrowType(
            Qt.DownArrow if expanded else Qt.RightArrow
        )
        self._toggle_btn.setStyleSheet(
            "QToolButton {"
            "  font-weight: bold;"
            "  font-size: 12px;"
            "  padding: 6px 8px;"
            "  border: 1px solid palette(mid);"
            "  border-radius: 4px;"
            "  text-align: left;"
            "}"
            "QToolButton:hover {"
            "  background-color: palette(midlight);"
            "}"
        )
        self._toggle_btn.toggled.connect(self._on_toggle)

        # Content frame
        self._content = QFrame()
        self._content.setFrameShape(QFrame.NoFrame)
        self._content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toggle_btn)
        layout.addWidget(self._content)
        self.setLayout(layout)

        if not expanded:
            self._content.setMaximumHeight(0)

    def set_content_layout(self, content_layout):
        """Define o layout interno da area de conteudo."""
        # Limpa layout anterior se existir
        old = self._content.layout()
        if old is not None:
            while old.count():
                item = old.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

        content_layout.setContentsMargins(8, 4, 4, 8)
        self._content.setLayout(content_layout)

        if self._expanded:
            self._content.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX

    def _on_toggle(self, checked):
        self._expanded = checked
        self._toggle_btn.setArrowType(
            Qt.DownArrow if checked else Qt.RightArrow
        )

        if checked:
            # Calcula altura necessaria
            target = self._content.sizeHint().height()
            if target <= 0:
                target = 16777215
        else:
            target = 0

        anim = QPropertyAnimation(self._content, b"maximumHeight")
        anim.setDuration(self._animation_duration)
        anim.setStartValue(self._content.maximumHeight())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.InOutQuad)

        if checked:
            # Ao terminar a expansao, remove limite de altura
            anim.finished.connect(
                lambda: self._content.setMaximumHeight(16777215)
            )

        # Guarda ref para nao ser GC'd
        self._current_anim = anim
        anim.start()
