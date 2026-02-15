"""Aba de mapeamentos — tabela paginada, buscavel, ordenavel."""

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
    QAbstractItemView, QFrame,
)

from qgis.core import QgsMessageLog, Qgis

from ...domain.models.enums import JobStatusEnum
from ...infra.config.settings import PLUGIN_NAME


class MapeamentosTab(QWidget):
    """Tabela de mapeamentos com busca, paginacao e detalhe."""

    # Mapeamento de colunas para campos de ordenacao no server
    _SORT_FIELDS = {
        0: "descricao",
        1: "dataReferencia",
    }

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller
        self._current_sort_col = 1
        self._current_sort_order = "desc"
        self._polling_timer = None
        self._polling_mapeamento_id = None
        self._detail_mapeamento = None

        self._build_ui()
        self._connect_signals()

        # Carrega mapeamentos se ja estiver autenticado (ex: sessao restaurada)
        if self._state.is_authenticated:
            self._controller.load_mapeamentos(page=0)

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Barra de busca
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Buscar mapeamentos...")
        self._search_input.setClearButtonEnabled(True)
        search_layout.addWidget(self._search_input)

        self._refresh_btn = QPushButton("Atualizar")
        self._refresh_btn.setFixedWidth(80)
        search_layout.addWidget(self._refresh_btn)
        layout.addLayout(search_layout)

        # Tabela
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Descricao", "Data Ref.", "Autor"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(False)  # Sorting via server
        self._table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        layout.addWidget(self._table)

        # Paginacao
        pag_layout = QHBoxLayout()
        self._prev_btn = QPushButton("Anterior")
        self._prev_btn.setFixedWidth(80)
        self._prev_btn.setEnabled(False)
        pag_layout.addWidget(self._prev_btn)

        pag_layout.addStretch()
        self._page_label = QLabel("Pagina 0 de 0")
        self._page_label.setAlignment(Qt.AlignCenter)
        pag_layout.addWidget(self._page_label)
        pag_layout.addStretch()

        self._next_btn = QPushButton("Proximo")
        self._next_btn.setFixedWidth(80)
        self._next_btn.setEnabled(False)
        pag_layout.addWidget(self._next_btn)
        layout.addLayout(pag_layout)

        # Loading / error feedback
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("font-size: 11px;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # Painel de detalhe expandivel
        self._detail_frame = QFrame()
        self._detail_frame.setFrameShape(QFrame.StyledPanel)
        self._detail_frame.setVisible(False)
        self._detail_layout = QVBoxLayout()
        self._detail_layout.setContentsMargins(8, 8, 8, 8)
        self._detail_layout.setSpacing(4)

        # Header do detalhe
        self._detail_header = QLabel()
        self._detail_header.setWordWrap(True)
        self._detail_header.setStyleSheet("font-size: 12px;")
        self._detail_layout.addWidget(self._detail_header)

        # Mini-tabela de metodos
        self._metodos_table = QTableWidget()
        self._metodos_table.setColumnCount(3)
        self._metodos_table.setHorizontalHeaderLabels(["Metodo", "Status", "Acao"])
        self._metodos_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._metodos_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._metodos_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._metodos_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._metodos_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._metodos_table.verticalHeader().setVisible(False)
        self._metodos_table.setMaximumHeight(150)
        self._detail_layout.addWidget(self._metodos_table)

        self._detail_frame.setLayout(self._detail_layout)
        layout.addWidget(self._detail_frame)

        # Polling timer (3s para metodos PROCESSING)
        self._polling_timer = QTimer(self)
        self._polling_timer.setInterval(3000)
        self._polling_timer.timeout.connect(self._on_polling_tick)

        self.setLayout(layout)

        # Debounce timer para busca (500ms)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(500)
        self._search_timer.timeout.connect(self._do_search)

    def _connect_signals(self):
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._refresh_btn.clicked.connect(self._on_refresh)
        self._prev_btn.clicked.connect(self._controller.previous_page)
        self._next_btn.clicked.connect(self._controller.next_page)
        self._table.currentCellChanged.connect(self._on_row_selected)

        self._state.mapeamentos_changed.connect(self._on_mapeamentos_changed)
        self._state.selected_mapeamento_changed.connect(self._on_detail_changed)
        self._state.loading_changed.connect(self._on_loading_changed)
        self._state.error_occurred.connect(self._on_error)
        self._state.auth_state_changed.connect(self._on_auth_changed)

    # ----------------------------------------------------------------
    # Event handlers
    # ----------------------------------------------------------------

    def _on_search_text_changed(self, text):
        self._search_timer.start()

    def _do_search(self):
        self._controller.search(self._search_input.text().strip())

    def _on_refresh(self):
        self._controller.load_mapeamentos()

    def _on_header_clicked(self, section):
        field = self._SORT_FIELDS.get(section)
        if not field:
            return

        if section == self._current_sort_col:
            self._current_sort_order = (
                "asc" if self._current_sort_order == "desc" else "desc"
            )
        else:
            self._current_sort_col = section
            self._current_sort_order = "asc"

        self._controller.sort(field, self._current_sort_order)

    def _on_row_selected(self, row, col, prev_row, prev_col):
        if row < 0 or not self._state.mapeamentos:
            return
        content = self._state.mapeamentos.content
        if row < len(content):
            mapeamento = content[row]
            self._controller.load_detail(mapeamento.id)

    def _on_auth_changed(self, is_authenticated):
        if is_authenticated:
            self._controller.load_mapeamentos(page=0)
        else:
            self._table.setRowCount(0)
            self._page_label.setText("Pagina 0 de 0")
            self._detail_frame.setVisible(False)

    # ----------------------------------------------------------------
    # State updates
    # ----------------------------------------------------------------

    def _on_mapeamentos_changed(self, result):
        if result is None:
            QgsMessageLog.logMessage(
                "[MapeamentosTab] Signal recebido mas result=None",
                PLUGIN_NAME, Qgis.Warning,
            )
            return

        QgsMessageLog.logMessage(
            f"[MapeamentosTab] Signal recebido: {len(result.content)} items, "
            f"page={result.page}/{result.total_pages}",
            PLUGIN_NAME, Qgis.Info,
        )
        self._table.setRowCount(0)
        self._table.setRowCount(len(result.content))

        for i, m in enumerate(result.content):
            # Descricao
            self._table.setItem(i, 0, QTableWidgetItem(m.descricao))

            # Data Referencia
            self._table.setItem(i, 1, QTableWidgetItem(m.data_referencia))

            # Autor
            self._table.setItem(i, 2, QTableWidgetItem(m.user_name or "-"))

        # Paginacao
        page = result.page + 1
        total = max(result.total_pages, 1)
        self._page_label.setText(f"Pagina {page} de {total}")
        self._prev_btn.setEnabled(result.page > 0)
        self._next_btn.setEnabled(result.page < result.total_pages - 1)

        self._status_label.setVisible(False)

    def _on_detail_changed(self, mapeamento):
        """Atualiza painel de detalhe com mini-tabela de metodos."""
        if mapeamento is None:
            self._detail_frame.setVisible(False)
            self._stop_polling()
            return

        self._detail_mapeamento = mapeamento

        # Header
        text = f"<b>{mapeamento.descricao}</b>"
        text += f" | {mapeamento.data_referencia}"
        if mapeamento.satelite:
            text += f" | {mapeamento.satelite}"
        self._detail_header.setText(text)

        # Mini-tabela de metodos
        self._metodos_table.setRowCount(0)
        self._metodos_table.setRowCount(len(mapeamento.metodos))

        has_processing = False
        for i, m in enumerate(mapeamento.metodos):
            # Metodo
            self._metodos_table.setItem(i, 0, QTableWidgetItem(m.metodo_apply))

            # Status chip
            status_item = QTableWidgetItem(m.status)
            try:
                status_enum = JobStatusEnum(m.status)
                status_item.setText(status_enum.label)
                status_item.setForeground(QColor(status_enum.color))
                if status_enum == JobStatusEnum.PROCESSING:
                    has_processing = True
            except ValueError:
                pass
            self._metodos_table.setItem(i, 1, status_item)

            # Botao de acao
            try:
                status_enum = JobStatusEnum(m.status)
                if status_enum == JobStatusEnum.DONE:
                    btn = QPushButton("Baixar")
                    btn.setStyleSheet(
                        "QPushButton { background-color: #1976D2; color: white; "
                        "border: none; padding: 2px 8px; border-radius: 3px; }"
                        "QPushButton:hover { background-color: #1565C0; }"
                        "QPushButton:disabled { background-color: #90CAF9; }"
                    )
                    metodo_id = m.id
                    mapeamento_id = mapeamento.id
                    btn.clicked.connect(
                        lambda checked, mid=mapeamento_id, met=metodo_id:
                        self._on_download_clicked(mid, met)
                    )
                    self._metodos_table.setCellWidget(i, 2, btn)
                elif status_enum == JobStatusEnum.PROCESSING:
                    lbl = QLabel("Aguardando...")
                    lbl.setAlignment(Qt.AlignCenter)
                    lbl.setStyleSheet("color: #FF9800; font-size: 11px;")
                    self._metodos_table.setCellWidget(i, 2, lbl)
                else:
                    self._metodos_table.setItem(i, 2, QTableWidgetItem("-"))
            except ValueError:
                self._metodos_table.setItem(i, 2, QTableWidgetItem("-"))

        self._detail_frame.setVisible(True)

        # Polling para metodos PROCESSING
        if has_processing:
            self._polling_mapeamento_id = mapeamento.id
            self._start_polling()
        else:
            self._stop_polling()

    def _on_download_clicked(self, mapeamento_id, metodo_id):
        """Inicia download da classificacao de um metodo."""
        self._controller.download_classification(mapeamento_id, metodo_id)

    def _start_polling(self):
        if not self._polling_timer.isActive():
            self._polling_timer.start()

    def _stop_polling(self):
        self._polling_timer.stop()
        self._polling_mapeamento_id = None

    def _on_polling_tick(self):
        if self._polling_mapeamento_id and self._state.is_authenticated:
            self._controller.load_detail(self._polling_mapeamento_id)

    def _on_loading_changed(self, operation, is_loading):
        if operation == "mapeamentos":
            self._refresh_btn.setEnabled(not is_loading)
            if is_loading:
                self._status_label.setText("Carregando...")
                self._status_label.setStyleSheet("font-size: 11px;")
                self._status_label.setVisible(True)
            else:
                self._status_label.setVisible(False)
        elif operation == "download":
            # Desabilita/habilita botoes de download na mini-tabela
            for row in range(self._metodos_table.rowCount()):
                widget = self._metodos_table.cellWidget(row, 2)
                if isinstance(widget, QPushButton):
                    widget.setEnabled(not is_loading)
                    widget.setText("Baixando..." if is_loading else "Baixar")

    def _on_error(self, operation, message):
        if operation in ("mapeamentos", "download"):
            self._status_label.setText(f"Erro: {message}")
            self._status_label.setStyleSheet("color: #F44336; font-size: 11px;")
            self._status_label.setVisible(True)
