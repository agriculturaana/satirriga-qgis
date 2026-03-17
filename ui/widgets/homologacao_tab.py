"""Aba de homologacao — tabela de zonais para aprovacao/reprovacao."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QAbstractItemView,
)

from qgis.core import QgsMessageLog, Qgis

from ...domain.models.enums import ZonalStatusEnum
from ...infra.config.settings import PLUGIN_NAME


# Filtros de status disponiveis
_STATUS_FILTERS = {
    "Aguardando": "AGUARDANDO",
    "Homologados": "HOMOLOGADO",
    "Reprovados": "REPROVADO",
    "Cancelados": "CANCELADO",
    "Todos": "AGUARDANDO,HOMOLOGADO,REPROVADO,CANCELADO",
}


class HomologacaoTab(QWidget):
    """Tabela dedicada para mapeamentos em homologacao."""

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller
        self._items = []

        self._build_ui()
        self._connect_signals()

        if self._state.is_authenticated:
            self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header com filtro
        header = QHBoxLayout()
        header.addWidget(QLabel("Homologação de mapeamentos"))
        header.addStretch()

        # Filtro de status
        self._status_filter = QComboBox()
        self._status_filter.setFixedWidth(130)
        for label in _STATUS_FILTERS:
            self._status_filter.addItem(label)
        self._status_filter.setCurrentIndex(0)  # Aguardando por padrao
        self._status_filter.currentIndexChanged.connect(self._on_filter_changed)
        header.addWidget(self._status_filter)

        self._refresh_btn = QPushButton("Atualizar")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._load_data)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # Tabela — 8 colunas
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "#ID", "Data Ref.", "Descrição", "Método", "Autor",
            "Status", "Features / Área", "Ações",
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

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
        self._state.catalogo_homologacao_changed.connect(self._on_data_loaded)
        self._state.parecer_emitido.connect(self._on_parecer_emitido)

    def _on_auth_changed(self, is_authenticated):
        if is_authenticated:
            self._load_data()
        else:
            self._table.setRowCount(0)

    def _on_filter_changed(self, _index):
        self._load_data()

    def _load_data(self):
        """Carrega catalogo de homologacao com filtro selecionado."""
        filter_text = self._status_filter.currentText()
        status = _STATUS_FILTERS.get(filter_text, "AGUARDANDO")
        self._controller.load_catalogo_homologacao(status_filter=status)

    def _on_data_loaded(self, items):
        """Atualiza tabela com itens recebidos."""
        self._items = items
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        if not items:
            self._status_label.setText("Nenhum mapeamento encontrado")
            self._status_label.setVisible(True)
            return

        self._status_label.setVisible(False)
        self._table.setRowCount(len(items))

        for i, item in enumerate(items):
            # #ID
            id_item = QTableWidgetItem()
            id_item.setData(Qt.DisplayRole, item.mapeamento_id or 0)
            self._table.setItem(i, 0, id_item)

            # Data Ref.
            data_ref = "—"
            if item.data_referencia:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(
                        item.data_referencia.replace("Z", "+00:00")
                    )
                    data_ref = dt.strftime("%d/%m/%Y")
                except (ValueError, AttributeError):
                    data_ref = item.data_referencia[:10]
            self._table.setItem(i, 1, QTableWidgetItem(data_ref))

            # Descricao
            desc_label = QLabel(item.descricao)
            desc_label.setTextFormat(Qt.RichText)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("padding: 2px 4px;")
            self._table.setCellWidget(i, 2, desc_label)

            # Metodo
            metodo = self._format_metodo(item.metodo_apply) if item.metodo_apply else "—"
            self._table.setItem(i, 3, QTableWidgetItem(metodo))

            # Autor
            self._table.setItem(i, 4, QTableWidgetItem(item.author or "—"))

            # Status chip
            status_item = QTableWidgetItem(item.status)
            try:
                status_enum = ZonalStatusEnum(item.status)
                status_item.setText(status_enum.label)
                status_item.setForeground(QColor(status_enum.color))
            except ValueError:
                pass
            self._table.setItem(i, 5, status_item)

            # Features / Area
            feat_area = f"{item.result_count or 0} / {(item.total_area_ha or 0):,.1f} ha"
            self._table.setItem(i, 6, QTableWidgetItem(feat_area))

            # Acoes
            actions = self._build_action_buttons(item)
            self._table.setCellWidget(i, 7, actions)

        self._table.resizeRowsToContents()

    def _build_action_buttons(self, item):
        """Cria botoes de acao condicionais ao status."""
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        # Baixar — sempre disponivel
        btn_download = QPushButton("Baixar")
        btn_download.setFixedWidth(50)
        btn_download.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "border: none; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        btn_download.clicked.connect(
            lambda _, zid=item.id, ci=item: self._on_download(zid, ci)
        )
        layout.addWidget(btn_download)

        # Aprovar e Reprovar — apenas para AGUARDANDO
        if item.status == "AGUARDANDO":
            btn_aprovar = QPushButton("Aprovar")
            btn_aprovar.setFixedWidth(55)
            btn_aprovar.setStyleSheet(
                "QPushButton { background-color: #2E7D32; color: white; "
                "border: none; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #1B5E20; }"
            )
            btn_aprovar.clicked.connect(
                lambda _, zid=item.id: self._on_parecer(zid)
            )
            layout.addWidget(btn_aprovar)

            btn_reprovar = QPushButton("Reprovar")
            btn_reprovar.setFixedWidth(60)
            btn_reprovar.setStyleSheet(
                "QPushButton { background-color: #C62828; color: white; "
                "border: none; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #B71C1C; }"
            )
            btn_reprovar.clicked.connect(
                lambda _, zid=item.id: self._on_parecer(zid)
            )
            layout.addWidget(btn_reprovar)

        widget.setLayout(layout)
        return widget

    def _on_download(self, zonal_id, catalogo_item):
        """Inicia download do zonal."""
        self._controller.download_zonal_result(zonal_id, catalogo_item=catalogo_item)

    def _on_parecer(self, zonal_id):
        """Abre dialogo de parecer para o zonal."""
        from ..dialogs.parecer_dialog import ParecerDialog

        dialog = ParecerDialog(zonal_id, parent=self)
        if dialog.exec_() == ParecerDialog.Accepted:
            result = dialog.get_result()
            if result:
                decisao, motivo = result
                self._controller.emitir_parecer(zonal_id, decisao, motivo)

    def _on_parecer_emitido(self, data):
        """Parecer emitido — recarrega lista."""
        self._load_data()

    def _on_loading_changed(self, operation, is_loading):
        if operation == "catalogo_homologacao":
            self._refresh_btn.setEnabled(not is_loading)
            if is_loading:
                self._status_label.setText("Carregando...")
                self._status_label.setStyleSheet("font-size: 11px;")
                self._status_label.setVisible(True)
            else:
                self._status_label.setVisible(False)
        elif operation == "download":
            for row in range(self._table.rowCount()):
                widget = self._table.cellWidget(row, 7)
                if widget:
                    for btn in widget.findChildren(QPushButton):
                        if btn.text() == "Baixar":
                            btn.setEnabled(not is_loading)

    def _on_error(self, operation, message):
        if operation in ("catalogo_homologacao", "parecer"):
            self._status_label.setText(f"Erro: {message}")
            self._status_label.setStyleSheet("color: #F44336; font-size: 11px;")
            self._status_label.setVisible(True)

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