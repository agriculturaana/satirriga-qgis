"""Tema centralizado — QSS aplicado ao dock container.

Usa cores da palette do sistema/QGIS por padrao.
Apenas bordas, padding e elementos de accent sao estilizados explicitamente.
"""

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
"""
