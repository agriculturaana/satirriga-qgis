"""Dialog de resolucao de conflitos de upload zonal."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QDialogButtonBox,
)

from ...domain.models.conflict import ConflictSet
from ...domain.models.enums import ConflictResolutionEnum


class ConflictResolutionDialog(QDialog):
    """Dialog para resolucao de conflitos detectados durante upload."""

    resolved = pyqtSignal(list)  # lista de {"featureHash": str, "resolution": str}

    def __init__(self, conflict_set: ConflictSet, parent=None):
        super().__init__(parent)
        self._conflict_set = conflict_set
        self._combos = []
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("Resolucao de Conflitos")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        layout = QVBoxLayout()

        # Header
        count = len(self._conflict_set.items)
        header = QLabel(f"<b>Conflitos detectados ({count} features)</b>")
        header.setStyleSheet("font-size: 14px;")
        layout.addWidget(header)

        # Info versao
        info = QLabel(
            f"Versao base: {self._conflict_set.base_version} "
            f"-> Versao atual: {self._conflict_set.current_version}"
        )
        info.setStyleSheet("font-size: 11px; color: #616161;")
        layout.addWidget(info)

        if self._conflict_set.expires_at:
            expires = QLabel(f"Expira em: {self._conflict_set.expires_at}")
            expires.setStyleSheet("font-size: 10px; color: #9E9E9E;")
            layout.addWidget(expires)

        # Tabela de conflitos
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            "Feature Hash", "Tipo", "Sugerido", "Decisao"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)

        self._table.setRowCount(count)
        self._combos = []

        for i, item in enumerate(self._conflict_set.items):
            # Feature hash (truncado)
            hash_text = item.feature_hash[:12] + "..." if len(item.feature_hash) > 12 else item.feature_hash
            self._table.setItem(i, 0, QTableWidgetItem(hash_text))
            self._table.item(i, 0).setToolTip(item.feature_hash)

            # Tipo de conflito
            self._table.setItem(i, 1, QTableWidgetItem(item.conflict_type))

            # Sugerido
            suggested = item.suggested or "-"
            self._table.setItem(i, 2, QTableWidgetItem(suggested))

            # ComboBox de decisao
            combo = QComboBox()
            combo.addItem("Minha versao", ConflictResolutionEnum.TAKE_MINE.value)
            combo.addItem("Versao servidor", ConflictResolutionEnum.TAKE_THEIRS.value)
            combo.addItem("Merge", ConflictResolutionEnum.MERGE.value)

            # Pre-seleciona sugerido se disponivel
            if item.suggested:
                for idx in range(combo.count()):
                    if combo.itemData(idx) == item.suggested:
                        combo.setCurrentIndex(idx)
                        break

            self._combos.append(combo)
            self._table.setCellWidget(i, 3, combo)

        layout.addWidget(self._table)

        # Botoes em lote
        batch_layout = QHBoxLayout()

        btn_all_mine = QPushButton("Aceitar Todas Minhas")
        btn_all_mine.setToolTip("Resolver todos os conflitos mantendo suas alteracoes locais")
        btn_all_mine.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; "
            "border: none; padding: 4px 12px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #F57C00; }"
        )
        btn_all_mine.clicked.connect(self._set_all_mine)
        batch_layout.addWidget(btn_all_mine)

        btn_all_theirs = QPushButton("Aceitar Todas Servidor")
        btn_all_theirs.setToolTip("Resolver todos os conflitos mantendo a versao do servidor")
        btn_all_theirs.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "border: none; padding: 4px 12px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        btn_all_theirs.clicked.connect(self._set_all_theirs)
        batch_layout.addWidget(btn_all_theirs)

        batch_layout.addStretch()
        layout.addLayout(batch_layout)

        # Botoes de acao
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancelar Upload")
        btn_cancel.setToolTip("Cancelar upload e descartar resolucoes")
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "border: none; padding: 6px 16px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #D32F2F; }"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_apply = QPushButton("Aplicar")
        btn_apply.setToolTip("Enviar resolucoes de conflitos ao servidor")
        btn_apply.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border: none; padding: 6px 16px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #388E3C; }"
        )
        btn_apply.clicked.connect(self._apply_resolutions)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _set_all_mine(self):
        for combo in self._combos:
            for idx in range(combo.count()):
                if combo.itemData(idx) == ConflictResolutionEnum.TAKE_MINE.value:
                    combo.setCurrentIndex(idx)
                    break

    def _set_all_theirs(self):
        for combo in self._combos:
            for idx in range(combo.count()):
                if combo.itemData(idx) == ConflictResolutionEnum.TAKE_THEIRS.value:
                    combo.setCurrentIndex(idx)
                    break

    def _apply_resolutions(self):
        """Emite lista de resolucoes e fecha dialog."""
        resolutions = []
        for i, item in enumerate(self._conflict_set.items):
            combo = self._combos[i]
            resolution = combo.currentData()
            resolutions.append({
                "featureHash": item.feature_hash,
                "resolution": resolution,
            })

        self.resolved.emit(resolutions)
        self.accept()
