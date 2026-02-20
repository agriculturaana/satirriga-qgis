"""Aba de camadas locais — lista GPKGs V2, sync status, acoes."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox,
)
from qgis.core import QgsProject, QgsVectorLayer, QgsMessageLog, Qgis

from ...domain.models.enums import SyncStatusEnum
from ...infra.config.settings import PLUGIN_NAME
from .upload_progress_widget import UploadProgressWidget


# Cores por sync status
_SYNC_COLORS = {
    "DOWNLOADED": "#2196F3",   # azul
    "MODIFIED": "#FF9800",     # laranja
    "UPLOADED": "#4CAF50",     # verde
    "NEW": "#9C27B0",          # roxo
}


class CamadasTab(QWidget):
    """Lista GPKGs locais com status de sync e acoes."""

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller
        self._gpkg_list = []
        self._active_batch_uuid = None

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Camadas locais (GeoPackage)"))
        header.addStretch()
        self._refresh_btn = QPushButton("Atualizar")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.setToolTip("Atualizar lista de camadas locais")
        self._refresh_btn.clicked.connect(self._refresh_list)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # Tabela — 4 colunas
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            "Zonal", "Sync Status", "Tamanho", "Acoes"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        # Upload progress widget (inicialmente hidden)
        self._upload_progress = UploadProgressWidget()
        self._upload_progress.cancelled.connect(self._on_upload_cancelled)
        layout.addWidget(self._upload_progress)

        # Loading / status
        self._status_label = QLabel("Nenhuma camada local encontrada")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("color: #757575; font-size: 11px;")
        layout.addWidget(self._status_label)

        self.setLayout(layout)

    def _connect_signals(self):
        self._state.auth_state_changed.connect(self._on_auth_changed)
        self._state.loading_changed.connect(self._on_loading_changed)
        self._state.upload_progress_changed.connect(self._on_upload_progress)

        self._controller.zonal_upload_completed.connect(
            lambda path, zid: self._on_zonal_upload_done()
        )

    def _on_auth_changed(self, is_authenticated):
        if is_authenticated:
            self._refresh_list()

    def _on_loading_changed(self, operation, is_loading):
        if operation == "upload":
            for row in range(self._table.rowCount()):
                widget = self._table.cellWidget(row, 3)
                if widget:
                    for btn in widget.findChildren(QPushButton):
                        btn.setEnabled(not is_loading)

    def _on_upload_progress(self, status_data):
        """Atualiza widget de progresso de upload."""
        self._upload_progress.update_from_status(status_data)
        self._upload_progress.setVisible(True)
        self._active_batch_uuid = status_data.get("batchUuid", self._active_batch_uuid)

        from ...domain.models.enums import UploadBatchStatusEnum
        status = status_data.get("status", "")
        try:
            if UploadBatchStatusEnum(status).is_terminal:
                from qgis.PyQt.QtCore import QTimer
                QTimer.singleShot(3000, self._upload_progress.finish)
        except ValueError:
            pass

    def _on_zonal_upload_done(self):
        """Upload zonal concluido — refresh lista."""
        self._refresh_list()

    def _on_upload_cancelled(self):
        """Usuario cancelou upload via widget de progresso."""
        QgsMessageLog.logMessage(
            f"Upload cancelado pelo usuario: batch {self._active_batch_uuid}",
            PLUGIN_NAME, Qgis.Info,
        )

    def _refresh_list(self):
        """Atualiza lista de GPKGs locais com status de sync."""
        from ...domain.services.gpkg_service import (
            list_local_gpkgs, gpkg_base_dir, count_features_by_sync_status,
        )

        try:
            base_dir = gpkg_base_dir()
            raw_list = list_local_gpkgs(base_dir)
            for entry in raw_list:
                entry["sync_counts"] = count_features_by_sync_status(entry["path"])
            self._gpkg_list = raw_list
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Erro ao listar GPKGs: {e}", PLUGIN_NAME, Qgis.Warning,
            )
            self._gpkg_list = []

        self._update_table()

    def _update_table(self):
        self._table.setRowCount(0)

        if not self._gpkg_list:
            self._status_label.setText("Nenhuma camada local encontrada")
            self._status_label.setVisible(True)
            return

        self._status_label.setVisible(False)
        self._table.setRowCount(len(self._gpkg_list))

        for i, gpkg_info in enumerate(self._gpkg_list):
            zid = gpkg_info.get("zonal_id", "?")

            # Coluna 0: Zonal
            self._table.setItem(i, 0, QTableWidgetItem(f"Zonal {zid}"))

            # Coluna 1: Sync status
            counts = gpkg_info.get("sync_counts", {})
            sync_item = self._build_sync_status_item(counts)
            self._table.setItem(i, 1, sync_item)

            # Coluna 2: Tamanho
            size = gpkg_info.get("size_mb", 0)
            self._table.setItem(i, 2, QTableWidgetItem(f"{size} MB"))

            # Coluna 3: Acoes
            actions_widget = self._build_action_buttons(i, gpkg_info, counts)
            self._table.setCellWidget(i, 3, actions_widget)

        self._table.resizeRowsToContents()

    def _build_sync_status_item(self, counts):
        """Cria item de tabela com resumo de sync status colorido."""
        modified = counts.get("MODIFIED", 0)
        new = counts.get("NEW", 0)
        uploaded = counts.get("UPLOADED", 0)
        downloaded = counts.get("DOWNLOADED", 0)
        total = counts.get("total", 0)

        if new > 0 and modified > 0:
            text = f"{modified} editada(s), {new} nova(s)"
            color = _SYNC_COLORS["MODIFIED"]
        elif new > 0:
            text = f"{new} nova(s)"
            color = _SYNC_COLORS["NEW"]
        elif modified > 0:
            text = f"{modified} editada(s)"
            color = _SYNC_COLORS["MODIFIED"]
        elif uploaded > 0 and uploaded == total:
            text = "Tudo enviado"
            color = _SYNC_COLORS["UPLOADED"]
        elif downloaded > 0:
            text = "Sincronizado"
            color = _SYNC_COLORS["DOWNLOADED"]
        else:
            text = f"{total} feat."
            color = "#757575"

        item = QTableWidgetItem(text)
        item.setForeground(QColor(color))
        return item

    def _build_action_buttons(self, row, gpkg_info, counts):
        """Cria widget com botoes de acao para cada GPKG."""
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        path = gpkg_info.get("path", "")
        zonal_id = gpkg_info.get("zonal_id")
        modified = counts.get("MODIFIED", 0)
        new = counts.get("NEW", 0)
        has_changes = modified > 0 or new > 0

        # Botao Abrir
        btn_open = QPushButton("Abrir")
        btn_open.setFixedWidth(50)
        btn_open.setToolTip("Abrir GeoPackage como camada editavel no QGIS")
        btn_open.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "border: none; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        btn_open.clicked.connect(
            lambda _, p=path, zid=zonal_id: self._open_gpkg(p, zid)
        )
        layout.addWidget(btn_open)

        # Botao Upload
        btn_upload = QPushButton("Enviar")
        btn_upload.setFixedWidth(50)

        if has_changes:
            btn_upload.setEnabled(True)
            btn_upload.setStyleSheet(
                "QPushButton { background-color: #FF9800; color: white; "
                "border: none; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #F57C00; }"
            )
            btn_upload.setToolTip(f"{modified + new} feature(s) para enviar")
            btn_upload.clicked.connect(
                lambda _, p=path: self._upload_gpkg(p)
            )
        else:
            btn_upload.setEnabled(False)
            btn_upload.setStyleSheet(
                "QPushButton { background-color: #E0E0E0; color: #9E9E9E; "
                "border: none; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
            )
            btn_upload.setToolTip("Sem alteracoes para enviar")

        layout.addWidget(btn_upload)

        # Botao Remover
        btn_remove = QPushButton("X")
        btn_remove.setFixedWidth(24)
        btn_remove.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "border: none; padding: 2px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #D32F2F; }"
        )
        btn_remove.setToolTip("Remover GeoPackage local")
        btn_remove.clicked.connect(
            lambda _, p=path, mod=modified + new: self._remove_gpkg(p, mod)
        )
        layout.addWidget(btn_remove)

        widget.setLayout(layout)
        return widget

    def _open_gpkg(self, gpkg_path, zonal_id):
        """Carrega GPKG como camada editavel no QGIS com edit tracking."""
        layer_name = f"Zonal {zonal_id}" if zonal_id else os.path.basename(gpkg_path)

        # Verifica se ja esta carregada
        for existing in QgsProject.instance().mapLayers().values():
            if existing.source() == gpkg_path:
                QgsMessageLog.logMessage(
                    f"Camada ja carregada: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
                )
                return

        layer = QgsVectorLayer(gpkg_path, layer_name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)

            if zonal_id is not None:
                self._controller.connect_edit_tracking(
                    layer, zonal_id=zonal_id,
                )

            QgsMessageLog.logMessage(
                f"Camada aberta: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
            )
        else:
            QgsMessageLog.logMessage(
                f"Falha ao abrir GPKG: {gpkg_path}", PLUGIN_NAME, Qgis.Warning,
            )

    def _upload_gpkg(self, gpkg_path):
        """Inicia upload de features modificadas."""
        if not self._state.is_authenticated:
            self._state.set_error("upload", "Nao autenticado")
            return

        self._controller.upload_zonal_edits(gpkg_path)

    def _remove_gpkg(self, gpkg_path, modified_count):
        """Remove GPKG local com confirmacao se ha edicoes pendentes."""
        if modified_count > 0:
            reply = QMessageBox.question(
                self,
                "Confirmar remocao",
                f"Este GPKG tem {modified_count} feature(s) editada(s) nao enviada(s).\n"
                "Deseja remover mesmo assim?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            # Remove camada do projeto se carregada
            for layer_id, layer in QgsProject.instance().mapLayers().items():
                if layer.source() == gpkg_path:
                    QgsProject.instance().removeMapLayer(layer_id)

            os.remove(gpkg_path)

            # Remove sidecar
            from ...domain.services.gpkg_service import sidecar_path
            sc_path = sidecar_path(gpkg_path)
            if os.path.exists(sc_path):
                os.remove(sc_path)

            QgsMessageLog.logMessage(
                f"GPKG removido: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
            )
            self._refresh_list()
        except OSError as e:
            QgsMessageLog.logMessage(
                f"Erro ao remover GPKG: {e}", PLUGIN_NAME, Qgis.Warning,
            )

    def refresh(self):
        """API publica para atualizar lista de camadas."""
        self._refresh_list()

    def add_gpkg_entry(self, gpkg_info):
        """Adiciona uma entrada de GPKG apos download."""
        self._refresh_list()
