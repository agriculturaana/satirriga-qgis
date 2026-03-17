"""Dialogo de emissao de parecer de homologacao."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QPlainTextEdit, QPushButton, QButtonGroup, QWidget,
)


class ParecerDialog(QDialog):
    """Dialogo para emissao de parecer (Aprovar / Reprovar / Cancelar).

    Retorna (decisao, motivo) via result() ou None se cancelado.
    """

    # Decisoes possiveis (valores conforme enum ParecerDecisao do backend)
    APROVAR = "APROVADO"
    REPROVAR = "REPROVADO"
    CANCELAR = "CANCELADO"

    _MIN_MOTIVO_CHARS = 20

    def __init__(self, zonal_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Emitir Parecer — Zonal #{zonal_id}")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._decisao = None
        self._motivo = ""

        self._build_ui()
        self._connect_signals()
        self._validate()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Instrucao
        layout.addWidget(QLabel("Selecione a decisão do parecer:"))

        # Radio buttons
        self._radio_group = QButtonGroup(self)
        self._radio_aprovar = QRadioButton("Aprovar (Homologar)")
        self._radio_reprovar = QRadioButton("Reprovar")
        self._radio_cancelar = QRadioButton("Cancelar mapeamento")

        self._radio_aprovar.setStyleSheet("color: #2E7D32; font-weight: bold;")
        self._radio_reprovar.setStyleSheet("color: #C62828; font-weight: bold;")
        self._radio_cancelar.setStyleSheet("color: #616161; font-weight: bold;")

        self._radio_group.addButton(self._radio_aprovar, 1)
        self._radio_group.addButton(self._radio_reprovar, 2)
        self._radio_group.addButton(self._radio_cancelar, 3)

        layout.addWidget(self._radio_aprovar)
        layout.addWidget(self._radio_reprovar)
        layout.addWidget(self._radio_cancelar)

        # Motivo (obrigatorio para reprovar/cancelar)
        self._motivo_label = QLabel("Motivo (obrigatório para reprovar/cancelar):")
        layout.addWidget(self._motivo_label)

        self._motivo_edit = QPlainTextEdit()
        self._motivo_edit.setPlaceholderText(
            f"Descreva o motivo (mínimo {self._MIN_MOTIVO_CHARS} caracteres)..."
        )
        self._motivo_edit.setMaximumHeight(100)
        layout.addWidget(self._motivo_edit)

        # Contador de caracteres
        self._char_counter = QLabel(f"0 / {self._MIN_MOTIVO_CHARS}")
        self._char_counter.setStyleSheet("color: #757575; font-size: 11px;")
        self._char_counter.setAlignment(Qt.AlignRight)
        layout.addWidget(self._char_counter)

        # Botoes
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_cancel = QPushButton("Cancelar")
        self._btn_cancel.setFixedWidth(90)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_confirm = QPushButton("Confirmar")
        self._btn_confirm.setFixedWidth(100)
        self._btn_confirm.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "border: none; padding: 6px 12px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1565C0; }"
            "QPushButton:disabled { background-color: #90CAF9; }"
        )
        btn_layout.addWidget(self._btn_confirm)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _connect_signals(self):
        self._radio_group.buttonClicked.connect(lambda _: self._validate())
        self._motivo_edit.textChanged.connect(self._on_motivo_changed)
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_confirm.clicked.connect(self._on_confirm)

    def _on_motivo_changed(self):
        count = len(self._motivo_edit.toPlainText().strip())
        self._char_counter.setText(f"{count} / {self._MIN_MOTIVO_CHARS}")
        if self._requires_motivo() and count < self._MIN_MOTIVO_CHARS:
            self._char_counter.setStyleSheet("color: #C62828; font-size: 11px;")
        else:
            self._char_counter.setStyleSheet("color: #757575; font-size: 11px;")
        self._validate()

    def _requires_motivo(self):
        """Motivo obrigatorio para reprovar e cancelar."""
        checked = self._radio_group.checkedId()
        return checked in (2, 3)  # reprovar ou cancelar

    def _validate(self):
        checked = self._radio_group.checkedId()
        if checked < 0:
            self._btn_confirm.setEnabled(False)
            return

        if self._requires_motivo():
            motivo_len = len(self._motivo_edit.toPlainText().strip())
            self._btn_confirm.setEnabled(motivo_len >= self._MIN_MOTIVO_CHARS)
            self._motivo_label.setVisible(True)
            self._motivo_edit.setVisible(True)
            self._char_counter.setVisible(True)
        else:
            self._btn_confirm.setEnabled(True)
            # Para aprovacao, motivo e opcional — manter visivel mas nao obrigatorio
            self._motivo_label.setVisible(True)
            self._motivo_edit.setVisible(True)
            self._char_counter.setVisible(True)

    def _on_confirm(self):
        checked = self._radio_group.checkedId()
        if checked == 1:
            self._decisao = self.APROVAR
        elif checked == 2:
            self._decisao = self.REPROVAR
        elif checked == 3:
            self._decisao = self.CANCELAR
        else:
            return

        self._motivo = self._motivo_edit.toPlainText().strip()
        self.accept()

    def get_result(self):
        """Retorna (decisao, motivo) ou None se cancelado."""
        if self._decisao:
            return (self._decisao, self._motivo)
        return None