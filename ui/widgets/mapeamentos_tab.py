"""Aba de catalogo zonal — tabela de zonais disponiveis para download."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QAbstractItemView,
)

from qgis.core import QgsMessageLog, Qgis

from ...domain.models.enums import ZonalStatusEnum
from ...infra.config.settings import PLUGIN_NAME


class MapeamentosTab(QWidget):
    """Catalogo de zonais disponiveis para download."""

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller

        self._build_ui()
        self._connect_signals()

        if self._state.is_authenticated:
            self._controller.load_catalogo()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Zonais disponíveis para download"))
        header.addStretch()
        self._refresh_btn = QPushButton("Atualizar")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.setToolTip("Atualizar lista de zonais disponíveis")
        self._refresh_btn.clicked.connect(self._on_catalogo_refresh)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # Tabela de catalogo
        self._cat_table = QTableWidget()
        self._cat_table.setColumnCount(8)
        self._cat_table.setHorizontalHeaderLabels([
            "#ID", "Data Ref.", "Descrição", "Método", "Autor",
            "Status", "Features / Área", "Ação",
        ])
        self._cat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._cat_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self._cat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._cat_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._cat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cat_table.verticalHeader().setVisible(False)
        layout.addWidget(self._cat_table)

        # Status label
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("font-size: 11px; color: #757575;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self.setLayout(layout)

    def _connect_signals(self):
        self._state.loading_changed.connect(self._on_loading_changed)
        self._state.error_occurred.connect(self._on_error)
        self._state.auth_state_changed.connect(self._on_auth_changed)
        self._state.catalogo_changed.connect(self._on_catalogo_changed)

    # ----------------------------------------------------------------
    # Event handlers
    # ----------------------------------------------------------------

    def _on_catalogo_refresh(self):
        self._controller.load_catalogo()

    def _on_auth_changed(self, is_authenticated):
        if is_authenticated:
            self._controller.load_catalogo()
        else:
            self._cat_table.setRowCount(0)

    # ----------------------------------------------------------------
    # Catalogo Zonal
    # ----------------------------------------------------------------

    def _on_catalogo_changed(self, items):
        """Atualiza tabela do catalogo zonal."""
        self._cat_table.setSortingEnabled(False)
        self._cat_table.setRowCount(0)

        if not items:
            self._status_label.setText("Nenhum zonal disponível")
            self._status_label.setVisible(True)
            return

        self._status_label.setVisible(False)
        self._cat_table.setRowCount(len(items))

        for i, item in enumerate(items):
            # #ID (mapeamento)
            id_item = QTableWidgetItem()
            id_item.setData(Qt.DisplayRole, item.mapeamento_id or 0)
            self._cat_table.setItem(i, 0, id_item)

            # Data Ref. (dd/mm/yyyy)
            data_ref = "—"
            if item.data_referencia:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(item.data_referencia.replace("Z", "+00:00"))
                    data_ref = dt.strftime("%d/%m/%Y")
                except (ValueError, AttributeError):
                    data_ref = item.data_referencia[:10]
            self._cat_table.setItem(i, 1, QTableWidgetItem(data_ref))

            # Descricao (renderiza HTML)
            desc_label = QLabel(item.descricao)
            desc_label.setTextFormat(Qt.RichText)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("padding: 2px 4px;")
            self._cat_table.setCellWidget(i, 2, desc_label)

            # Metodo
            metodo_label = self._format_metodo(item.metodo_apply) if item.metodo_apply else "—"
            self._cat_table.setItem(i, 3, QTableWidgetItem(metodo_label))

            # Autor
            self._cat_table.setItem(i, 4, QTableWidgetItem(item.author or "—"))

            # Status chip
            status_item = QTableWidgetItem(item.status)
            try:
                status_enum = ZonalStatusEnum(item.status)
                status_item.setText(status_enum.label)
                status_item.setForeground(QColor(status_enum.color))
            except ValueError:
                pass
            self._cat_table.setItem(i, 5, status_item)

            # Features / Area
            feat_area = f"{item.result_count or 0} / {(item.total_area_ha or 0):,.1f} ha"
            self._cat_table.setItem(i, 6, QTableWidgetItem(feat_area))

            # Botao download
            btn = QPushButton("Baixar")
            btn.setToolTip("Baixar resultado zonal como GeoPackage editável")
            btn.setStyleSheet(
                "QPushButton { background-color: #1976D2; color: white; "
                "border: none; padding: 2px 8px; border-radius: 3px; }"
                "QPushButton:hover { background-color: #1565C0; }"
                "QPushButton:disabled { background-color: #90CAF9; }"
            )
            zonal_id = item.id
            btn.clicked.connect(
                lambda checked, zid=zonal_id, ci=item: self._on_zonal_download_clicked(zid, ci)
            )
            self._cat_table.setCellWidget(i, 7, btn)

        self._cat_table.resizeRowsToContents()

    @staticmethod
    def _format_metodo(metodo_apply):
        """Converte metodoApply em label legivel."""
        labels = {
            "METODO_1": "Método 1",
            "METODO_2_DISCRETO": "Método 2a (Discreto)",
            "METODO_2_FUZZY": "Método 2b (Fuzzy)",
            "METODO_3": "Método 3",
        }
        return labels.get(metodo_apply, metodo_apply)

    def _on_zonal_download_clicked(self, zonal_id, catalogo_item=None):
        """Inicia download do resultado zonal."""
        self._controller.download_zonal_result(zonal_id, catalogo_item=catalogo_item)

    # ----------------------------------------------------------------
    # Loading / Error
    # ----------------------------------------------------------------

    def _on_loading_changed(self, operation, is_loading):
        if operation == "download":
            for row in range(self._cat_table.rowCount()):
                widget = self._cat_table.cellWidget(row, 7)
                if isinstance(widget, QPushButton):
                    widget.setEnabled(not is_loading)
                    widget.setText("Baixando..." if is_loading else "Baixar")
        elif operation == "catalogo":
            self._refresh_btn.setEnabled(not is_loading)
            if is_loading:
                self._status_label.setText("Carregando catálogo...")
                self._status_label.setStyleSheet("font-size: 11px;")
                self._status_label.setVisible(True)
            else:
                self._status_label.setVisible(False)

    def _on_error(self, operation, message):
        if operation == "catalogo":
            self._status_label.setText(f"Erro: {message}")
            self._status_label.setStyleSheet("color: #F44336; font-size: 11px;")
            self._status_label.setVisible(True)
