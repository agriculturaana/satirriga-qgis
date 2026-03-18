"""Diálogo de comparação entre versões de upload."""

from datetime import datetime

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QDialogButtonBox, QGroupBox,
)


class CompareDialog(QDialog):
    """Permite ao usuário selecionar duas versões para comparação no mapa."""

    def __init__(self, versions_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comparar versões")
        self.setMinimumWidth(400)

        self._versions = versions_data.get("versions", [])
        self._current_version = versions_data.get("currentVersion", 0)
        self._result = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout()

        info = QLabel(
            f"Versão atual do zonal: <b>v{self._current_version}</b><br>"
            f"<small>{len(self._versions)} versão(ões) disponível(is) para comparação.</small>"
        )
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        # Seleção de versões
        group = QGroupBox("Selecione as versões")
        group_layout = QVBoxLayout()

        # Versão A (mais antiga / base)
        row_a = QHBoxLayout()
        row_a.addWidget(QLabel("Versão base:"))
        self._combo_a = QComboBox()
        row_a.addWidget(self._combo_a, 1)
        group_layout.addLayout(row_a)

        # Versão B (mais recente / para comparar)
        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("Comparar com:"))
        self._combo_b = QComboBox()
        row_b.addWidget(self._combo_b, 1)
        group_layout.addLayout(row_b)

        group.setLayout(group_layout)
        layout.addWidget(group)

        # Preencher combos
        for v in self._versions:
            label = self._format_version(v)
            self._combo_a.addItem(label, v.get("batchUuid"))
            self._combo_b.addItem(label, v.get("batchUuid"))

        # Pré-selecionar: A = penúltimo, B = último
        if len(self._versions) >= 2:
            self._combo_a.setCurrentIndex(1)  # penúltimo (mais antigo)
            self._combo_b.setCurrentIndex(0)  # último (mais recente)

        # Legenda
        legend = QLabel(
            "<br><b>Legenda no mapa:</b><br>"
            "<span style='color:#4CAF50'>● CREATED</span> — feições novas<br>"
            "<span style='color:#FF9800'>● MODIFIED</span> — feições editadas<br>"
            "<span style='color:#F44336'>● DELETED</span> — feições removidas<br>"
            "<span style='color:#9E9E9E'>● ACCEPTED</span> — sem alteração"
        )
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet("font-size: 11px;")
        layout.addWidget(legend)

        # Botões
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText("Comparar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _format_version(self, v):
        """Formata label de versão para o combobox."""
        version = v.get("version", "?")
        author = (v.get("user") or {}).get("name", "?")
        created = v.get("createdAt", "")
        date_str = ""
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                date_str = dt.strftime("%d/%m/%Y %H:%M")
            except (ValueError, AttributeError):
                date_str = str(created)[:16]

        modified = v.get("modifiedCount", 0) or 0
        new = v.get("newCount", 0) or 0
        deleted = v.get("deletedCount", 0) or 0
        changes = f"{modified}ed/{new}new/{deleted}del"

        return f"v{version} — {date_str} — {author} ({changes})"

    def _on_accept(self):
        batch_a = self._combo_a.currentData()
        batch_b = self._combo_b.currentData()

        if batch_a == batch_b:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Mesma versão",
                "Selecione duas versões diferentes para comparação."
            )
            return

        self._result = (batch_a, batch_b)
        self.accept()

    def get_result(self):
        """Retorna (batchUuid_A, batchUuid_B) ou None."""
        return self._result
