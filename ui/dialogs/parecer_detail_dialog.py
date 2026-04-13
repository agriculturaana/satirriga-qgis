"""Dialog de visualização do histórico de pareceres de um mapeamento."""

import os
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame,
)

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)
from ..icon_utils import tinted_icon

# Estilo por decisão
_DECISAO_STYLES = {
    "APROVADO": ("#2E7D32", "#E8F5E9", "Aprovado"),
    "REPROVADO": ("#C62828", "#FFEBEE", "Reprovado"),
    "CANCELADO": ("#4E342E", "#EFEBE9", "Cancelado"),
    "DEVOLVIDO": ("#E65100", "#FFF3E0", "Devolvido"),
    "RETIRADO": ("#616161", "#F5F5F5", "Retirado"),
}


class ParecerDetailDialog(QDialog):
    """Exibe histórico de pareceres de um mapeamento."""

    def __init__(self, mapeamento_id, pareceres, parent=None):
        super().__init__(parent)
        self._mapeamento_id = mapeamento_id
        self._pareceres = pareceres
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle(f"Pareceres — Mapeamento #{self._mapeamento_id}")
        self.setMinimumWidth(480)
        self.setMaximumWidth(640)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel(
            f"<b>Histórico de pareceres</b> — Mapeamento #{self._mapeamento_id}"
        )
        header.setStyleSheet("font-size: 13px;")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Separador
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #E0E0E0;")
        layout.addWidget(sep)

        if not self._pareceres:
            empty = QLabel("Nenhum parecer registrado para este mapeamento.")
            empty.setStyleSheet("font-size: 12px; color: #757575; font-style: italic;")
            empty.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty)
        else:
            # Scroll area com cards de pareceres
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

            container = QWidget()
            container.setStyleSheet("background: transparent;")
            cards_layout = QVBoxLayout()
            cards_layout.setContentsMargins(0, 0, 0, 0)
            cards_layout.setSpacing(8)

            for parecer in self._pareceres:
                cards_layout.addWidget(self._build_parecer_card(parecer))

            cards_layout.addStretch()
            container.setLayout(cards_layout)
            scroll.setWidget(container)

            # Limita altura para não expandir demais
            max_height = min(400, 120 * len(self._pareceres) + 20)
            scroll.setMaximumHeight(max_height)
            layout.addWidget(scroll, 1)

        # Botão Fechar
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_close = QPushButton("Fechar")
        btn_close.setDefault(True)
        btn_close.setFixedWidth(80)
        btn_close.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "border: none; padding: 6px 16px; border-radius: 4px; "
            "font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _build_parecer_card(self, parecer):
        """Constrói card visual para um parecer individual."""
        decisao = parecer.get("decisao", "")
        style = _DECISAO_STYLES.get(decisao, ("#616161", "#F5F5F5", decisao))
        color, bg, label = style

        card = QFrame()
        card.setFrameShape(QFrame.NoFrame)
        card.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border-left: 4px solid {color};"
            f" border-radius: 4px; padding: 8px; }}"
        )

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(4)

        # Linha 1: decisão + data
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        badge = QLabel(label)
        badge.setStyleSheet(
            f"background-color: {color}; color: white;"
            " border-radius: 3px; padding: 2px 8px; font-size: 11px;"
            " font-weight: bold; border: none;"
        )
        row1.addWidget(badge)

        created_at = parecer.get("createdAt", "")
        date_str = self._format_date(created_at)
        date_label = QLabel(date_str)
        date_label.setStyleSheet(
            f"font-size: 11px; color: #757575; border: none; background: transparent;"
        )
        row1.addWidget(date_label)

        row1.addStretch()

        # Zonal ID
        zonal = parecer.get("zonal") or {}
        zonal_id = parecer.get("zonalId") or zonal.get("id", "")
        if zonal_id:
            zonal_label = QLabel(f"Zonal #{zonal_id}")
            zonal_label.setStyleSheet(
                "font-size: 10px; color: #9E9E9E; border: none; background: transparent;"
            )
            row1.addWidget(zonal_label)

        card_layout.addLayout(row1)

        # Linha 2: revisor
        user = parecer.get("user") or {}
        reviewer_name = user.get("name") or user.get("email") or "—"
        reviewer = QLabel(f"Revisor: <b>{reviewer_name}</b>")
        reviewer.setStyleSheet(
            f"font-size: 11px; color: {color}; border: none; background: transparent;"
        )
        reviewer.setTextFormat(Qt.RichText)
        card_layout.addWidget(reviewer)

        # Linha 3: motivo (se houver)
        motivo = parecer.get("motivo") or ""
        if motivo:
            motivo_label = QLabel(motivo)
            motivo_label.setWordWrap(True)
            motivo_label.setStyleSheet(
                "font-size: 11px; color: #424242; font-style: italic;"
                " border: none; background: transparent; padding-top: 2px;"
            )
            card_layout.addWidget(motivo_label)

        card.setLayout(card_layout)
        return card

    @staticmethod
    def _format_date(iso_str):
        """Formata data ISO para dd/mm/yyyy HH:MM."""
        if not iso_str:
            return "—"
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y %H:%M")
        except (ValueError, AttributeError):
            return iso_str[:16] if len(iso_str) >= 16 else iso_str
