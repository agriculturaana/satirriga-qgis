"""Dialog de erro/aviso para feedback intuitivo ao usuario."""

import os

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QWidget,
)

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)
from ..icon_utils import tinted_icon

# Mapeamento operacao -> titulo legivel
_OPERATION_LABELS = {
    "catalogo": "Catálogo Zonal",
    "download": "Download de Dados",
    "upload": "Upload de Edições",
    "auth": "Autenticação",
    "config": "Configuração",
    "conflict": "Resolução de Conflitos",
}

# Mapeamento operacao -> sugestao de acao
_OPERATION_HINTS = {
    "catalogo": "Verifique sua conexão e tente atualizar novamente.",
    "download": "Verifique sua conexão e tente o download novamente.",
    "upload": "Verifique sua conexão e tente o upload novamente.",
    "auth": "Tente efetuar login novamente.",
    "config": "Verifique as configurações do plugin.",
    "conflict": "Tente o upload novamente ou entre em contato com o suporte.",
}


class ErrorDialog(QDialog):
    """Dialog de erro com resumo visual e detalhes expandiveis."""

    def __init__(self, operation, message, parent=None):
        super().__init__(parent)
        self._operation = operation
        self._message = message
        self._details_visible = False
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("SatIrriga — Erro")
        self.setMinimumWidth(460)
        self.setMaximumWidth(600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- Header: icone + titulo ---
        header = QHBoxLayout()
        header.setSpacing(10)

        icon_label = QLabel("\u26a0")
        icon_label.setStyleSheet(
            "font-size: 28px; color: #F44336; padding: 0; margin: 0;"
        )
        icon_label.setFixedWidth(36)
        icon_label.setAlignment(Qt.AlignTop)
        header.addWidget(icon_label)

        title_block = QVBoxLayout()
        title_block.setSpacing(4)

        op_label = _OPERATION_LABELS.get(self._operation, self._operation.title())
        title = QLabel(f"Erro: {op_label}")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        title.setWordWrap(True)
        title_block.addWidget(title)

        # Mensagem resumida (primeira linha, sem stack trace)
        summary = self._extract_summary(self._message)
        summary_label = QLabel(summary)
        summary_label.setStyleSheet("font-size: 12px; color: #424242;")
        summary_label.setWordWrap(True)
        title_block.addWidget(summary_label)

        header.addLayout(title_block)
        layout.addLayout(header)

        # --- Hint ---
        hint = _OPERATION_HINTS.get(self._operation, "Tente novamente.")
        hint_label = QLabel(hint)
        hint_label.setStyleSheet(
            "font-size: 11px; color: #757575; font-style: italic;"
        )
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        # --- Separador ---
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #E0E0E0;")
        layout.addWidget(sep)

        # --- Detalhes expandiveis ---
        self._toggle_btn = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_info.svg"), "#1976D2"), "Mostrar detalhes")
        self._toggle_btn.setIconSize(QSize(14, 14))
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton { color: #1976D2; font-size: 11px; text-align: left; "
            "padding: 0; border: none; }"
            "QPushButton:hover { color: #1565C0; text-decoration: underline; }"
        )
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_details)
        layout.addWidget(self._toggle_btn)

        self._details_text = QTextEdit()
        self._details_text.setReadOnly(True)
        self._details_text.setPlainText(self._message)
        self._details_text.setFixedHeight(120)
        self._details_text.setStyleSheet(
            "QTextEdit { background-color: #FAFAFA; border: 1px solid #E0E0E0; "
            "border-radius: 4px; font-family: monospace; font-size: 11px; "
            "color: #616161; padding: 6px; }"
        )
        self._details_text.setVisible(False)
        layout.addWidget(self._details_text)

        # --- Botao OK ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)
        btn_ok.setFixedWidth(80)
        btn_ok.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "border: none; padding: 6px 16px; border-radius: 4px; "
            "font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _toggle_details(self):
        self._details_visible = not self._details_visible
        self._details_text.setVisible(self._details_visible)
        self._toggle_btn.setText(
            "Ocultar detalhes" if self._details_visible else "Mostrar detalhes"
        )
        self.adjustSize()

    @staticmethod
    def _extract_summary(message):
        """Extrai uma linha resumida da mensagem de erro."""
        if not message:
            return "Erro desconhecido"
        first_line = message.split("\n")[0].strip()
        # Limita tamanho para exibicao
        if len(first_line) > 200:
            return first_line[:197] + "..."
        return first_line

    @classmethod
    def show_error(cls, operation, message, parent=None):
        """Atalho para exibir dialog de erro."""
        dialog = cls(operation, message, parent=parent)
        dialog.exec_()
