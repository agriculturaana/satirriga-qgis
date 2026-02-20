"""Aba de catalogo zonal — tabela de zonais disponiveis para download."""

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
        header.addWidget(QLabel("Zonais disponiveis para download"))
        header.addStretch()
        self._refresh_btn = QPushButton("Atualizar")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.setToolTip("Atualizar lista de zonais disponiveis")
        self._refresh_btn.clicked.connect(self._on_catalogo_refresh)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # Tabela de catalogo
        self._cat_table = QTableWidget()
        self._cat_table.setColumnCount(5)
        self._cat_table.setHorizontalHeaderLabels([
            "Descricao", "Status", "Features", "Area (ha)", "Acao"
        ])
        self._cat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._cat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._cat_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._cat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._cat_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._cat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cat_table.verticalHeader().setVisible(False)

        # Tooltips nos headers
        header_view = self._cat_table.horizontalHeader()
        header_view.model().setHeaderData(1, header_view.orientation(), "Status do processamento", 3)
        header_view.model().setHeaderData(2, header_view.orientation(), "Numero de feicoes", 3)
        header_view.model().setHeaderData(3, header_view.orientation(), "Area total em hectares", 3)

        layout.addWidget(self._cat_table)

        # Status label
        self._status_label = QLabel()
        self._status_label.setAlignment(QLabel().alignment())
        from qgis.PyQt.QtCore import Qt
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
        self._cat_table.setRowCount(0)

        if not items:
            self._status_label.setText("Nenhum zonal disponivel")
            self._status_label.setVisible(True)
            return

        self._status_label.setVisible(False)
        self._cat_table.setRowCount(len(items))

        for i, item in enumerate(items):
            # Descricao
            self._cat_table.setItem(i, 0, QTableWidgetItem(item.descricao))

            # Status chip
            status_item = QTableWidgetItem(item.status)
            try:
                status_enum = ZonalStatusEnum(item.status)
                status_item.setText(status_enum.label)
                status_item.setForeground(QColor(status_enum.color))
            except ValueError:
                pass
            self._cat_table.setItem(i, 1, status_item)

            # Features count
            self._cat_table.setItem(
                i, 2, QTableWidgetItem(str(item.result_count))
            )

            # Area
            self._cat_table.setItem(
                i, 3, QTableWidgetItem(f"{item.total_area_ha:,.1f}")
            )

            # Botao download
            btn = QPushButton("Baixar")
            btn.setToolTip("Baixar resultado zonal como GeoPackage editavel")
            btn.setStyleSheet(
                "QPushButton { background-color: #1976D2; color: white; "
                "border: none; padding: 2px 8px; border-radius: 3px; }"
                "QPushButton:hover { background-color: #1565C0; }"
                "QPushButton:disabled { background-color: #90CAF9; }"
            )
            zonal_id = item.id
            btn.clicked.connect(
                lambda checked, zid=zonal_id: self._on_zonal_download_clicked(zid)
            )
            self._cat_table.setCellWidget(i, 4, btn)

        self._cat_table.resizeRowsToContents()

    def _on_zonal_download_clicked(self, zonal_id):
        """Inicia download do resultado zonal."""
        self._controller.download_zonal_result(zonal_id)

    # ----------------------------------------------------------------
    # Loading / Error
    # ----------------------------------------------------------------

    def _on_loading_changed(self, operation, is_loading):
        if operation == "download":
            for row in range(self._cat_table.rowCount()):
                widget = self._cat_table.cellWidget(row, 4)
                if isinstance(widget, QPushButton):
                    widget.setEnabled(not is_loading)
                    widget.setText("Baixando..." if is_loading else "Baixar")
        elif operation == "catalogo":
            self._refresh_btn.setEnabled(not is_loading)
            if is_loading:
                self._status_label.setText("Carregando catalogo...")
                self._status_label.setStyleSheet("font-size: 11px;")
                self._status_label.setVisible(True)
            else:
                self._status_label.setVisible(False)

    def _on_error(self, operation, message):
        if operation == "catalogo":
            self._status_label.setText(f"Erro: {message}")
            self._status_label.setStyleSheet("color: #F44336; font-size: 11px;")
            self._status_label.setVisible(True)
