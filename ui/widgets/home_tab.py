"""Home tab — branding e logos institucionais."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap, QPalette, QFont
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)

from ...infra.config.settings import PLUGIN_VERSION


_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_ASSETS_DIR = os.path.join(_PLUGIN_DIR, "assets")


class HomeTab(QWidget):
    """Tela inicial com branding SatIrriga e logos institucionais."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(0)

        pal = self.palette()
        mid_color = pal.color(QPalette.Mid).name()
        text_color = pal.color(QPalette.WindowText).name()

        # Logo SatIrriga
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        logo_path = os.path.join(_ASSETS_DIR, "logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(
                pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        logo_label.setFixedHeight(72)
        layout.addWidget(logo_label)

        # Titulo
        title = QLabel("SatIrriga")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        layout.addSpacing(4)

        # Subtitulo
        subtitle = QLabel("Monitoramento de Irrigacao por Satelite")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"font-size: 12px; color: {mid_color};")
        layout.addWidget(subtitle)

        layout.addSpacing(12)

        # Descricao
        desc = QLabel(
            "Plugin QGIS para classificacao e monitoramento\n"
            "de areas irrigadas via sensoriamento remoto."
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 11px; color: {text_color};")
        layout.addWidget(desc)

        # Spacer central
        layout.addStretch()

        # Separador
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(f"color: {mid_color};")
        separator.setFixedHeight(1)
        layout.addWidget(separator)

        layout.addSpacing(12)

        # Logos institucionais
        logos_layout = QHBoxLayout()
        logos_layout.setSpacing(24)
        logos_layout.setAlignment(Qt.AlignCenter)

        for name, filename in (("ANA", "ana.png"), ("INPE", "inpe.png")):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.setAlignment(Qt.AlignCenter)

            img_label = QLabel()
            img_label.setAlignment(Qt.AlignCenter)
            img_path = os.path.join(_ASSETS_DIR, "logos", filename)
            if os.path.exists(img_path):
                px = QPixmap(img_path)
                img_label.setPixmap(
                    px.scaledToHeight(40, Qt.SmoothTransformation)
                )
            col.addWidget(img_label)

            text_label = QLabel(name)
            text_label.setAlignment(Qt.AlignCenter)
            text_label.setStyleSheet(f"font-size: 10px; color: {mid_color};")
            col.addWidget(text_label)

            logos_layout.addLayout(col)

        layout.addLayout(logos_layout)

        layout.addSpacing(12)

        # Versao
        version_label = QLabel(f"v{PLUGIN_VERSION}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet(f"font-size: 10px; color: {mid_color};")
        layout.addWidget(version_label)

        self.setLayout(layout)
