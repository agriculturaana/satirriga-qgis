"""Tema centralizado — QSS e widgets de design system do dock.

Usa cores da palette do sistema/QGIS por padrao.
Apenas bordas, padding e elementos de accent sao estilizados explicitamente.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPainter, QFont
from qgis.PyQt.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSizePolicy,
)

# Paleta de cores do design system (tons escuros da logo SatIrriga)
ACCENT = "#1976D2"


class SectionHeader(QWidget):
    """Header padronizado para abas — barra accent à esquerda, fundo transparente."""

    def __init__(self, title, subtitle=None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(6)

        title_label = QLabel(title)
        font = QFont()
        font.setPixelSize(13)
        font.setBold(True)
        title_label.setFont(font)
        title_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(title_label)

        if subtitle:
            sub_label = QLabel(subtitle)
            sub_label.setStyleSheet(
                "color: #757575; font-size: 11px; border: none; background: transparent;"
            )
            layout.addWidget(sub_label)

        layout.addStretch()
        self._extra_layout = layout
        self.setLayout(layout)

    def add_widget(self, widget):
        """Adiciona widget ao lado direito do header (após o stretch)."""
        self._extra_layout.addWidget(widget)

    def paintEvent(self, event):
        painter = QPainter(self)
        # Barra accent esquerda
        painter.fillRect(0, 4, 3, self.height() - 8, QColor(ACCENT))
        # Linha inferior discreta
        painter.setPen(QColor(0, 0, 0, 18))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.end()

DOCK_STYLESHEET = """
/* Headers de tabela */
QHeaderView::section {
    font-weight: bold;
    border: none;
    border-bottom: 1px solid palette(mid);
    padding: 4px 8px;
    font-size: 12px;
}

/* Tabelas */
QTableWidget {
    border: 1px solid palette(mid);
    gridline-color: palette(midlight);
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    font-size: 12px;
}

QTableWidget::item {
    padding: 4px;
}

/* Inputs */
QLineEdit {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

QLineEdit:focus {
    border: 1px solid #1976D2;
}

/* ComboBox */
QComboBox {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

QComboBox:focus {
    border: 1px solid #1976D2;
}

/* SpinBox */
QSpinBox {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

/* ScrollBar vertical */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: palette(mid);
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: palette(dark);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    height: 0px;
}

/* ScrollBar horizontal */
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: palette(mid);
    border-radius: 4px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background: palette(dark);
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
    width: 0px;
}

/* PlainTextEdit (logs) */
QPlainTextEdit {
    border: 1px solid palette(mid);
    border-radius: 4px;
}

/* FormLayout labels */
QFormLayout QLabel {
    font-size: 12px;
}

/* Tooltips visiveis em qualquer tema */
QToolTip {
    background-color: #424242;
    color: #FFFFFF;
    border: 1px solid #616161;
    padding: 4px 8px;
    font-size: 11px;
    border-radius: 3px;
}
"""
