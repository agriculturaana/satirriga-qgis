"""Aba de logs — captura QgsMessageLog tag SatIrriga."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit,
    QPushButton, QLabel, QApplication,
)
from qgis.core import QgsApplication, QgsMessageLog

from ...infra.config.settings import PLUGIN_NAME


class LogsTab(QWidget):
    """Viewer de logs do plugin com captura de QgsMessageLog."""

    MAX_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._connect_log()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Logs do plugin"))
        header.addStretch()

        self._line_count = QLabel("0 linhas")
        self._line_count.setStyleSheet("font-size: 10px; color: #757575;")
        header.addWidget(self._line_count)
        layout.addLayout(header)

        # Text area
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(self.MAX_LINES)
        self._text.setStyleSheet(
            "QPlainTextEdit { font-family: monospace; font-size: 11px; "
            "background-color: #1E1E1E; color: #D4D4D4; }"
        )
        layout.addWidget(self._text)

        # Botoes
        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("Limpar")
        clear_btn.setFixedWidth(80)
        clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(clear_btn)

        copy_btn = QPushButton("Copiar")
        copy_btn.setFixedWidth(80)
        copy_btn.clicked.connect(self._on_copy)
        btn_layout.addWidget(copy_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _connect_log(self):
        QgsApplication.messageLog().messageReceived.connect(self._on_log_message)

    def _on_log_message(self, message, tag, level):
        if tag != PLUGIN_NAME:
            return

        level_prefix = {0: "INFO", 1: "WARN", 2: "CRIT", 3: "NONE"}.get(level, "???")
        line = f"[{level_prefix}] {message}"
        self._text.appendPlainText(line)

        count = self._text.blockCount()
        self._line_count.setText(f"{count} linhas")

    def _on_clear(self):
        self._text.clear()
        self._line_count.setText("0 linhas")

    def _on_copy(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self._text.toPlainText())
