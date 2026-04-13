"""Aba de homologação — cards de zonais para aprovação/reprovação."""

import os
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QSize, QTimer
from qgis.PyQt.QtGui import QColor, QIcon, QTextDocument, QFontMetrics
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLineEdit,
    QLabel, QListWidget, QListWidgetItem, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect, QMessageBox, QToolButton,
)

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)

from qgis.core import QgsMessageLog, Qgis

from ..theme import SectionHeader

from ...domain.models.enums import ZonalStatusEnum
from ...infra.config.settings import PLUGIN_NAME
from ..icon_utils import tinted_icon


# Opções de ordenação: label exibido → campo da API
_SORT_OPTIONS = [
    ("#ID", "mapeamentoId"),
    ("Data", "dataReferencia"),
    ("Autor", "author"),
    ("Descrição", "descricao"),
    ("Status", "status"),
    ("Editado em", "processedAt"),
]

# Filtros de status disponíveis
_STATUS_FILTERS = {
    "Aguardando": "AGUARDANDO",
    "Homologados": "HOMOLOGADO",
    "Reprovados": "REPROVADO",
    "Cancelados": "CANCELADO",
    "Todos": "AGUARDANDO,HOMOLOGADO,REPROVADO,CANCELADO",
}


class HomologacaoTab(QWidget):
    """Cards dedicados para mapeamentos em homologação."""

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller
        self._items = []
        self._current_page = 1
        self._total_pages = 1
        self._total_items = 0

        # Debounce para filtros textuais
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._load_data)

        self._build_ui()
        self._connect_signals()

        if self._state.is_authenticated:
            self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        section_header = SectionHeader("Homologação", "mapeamentos")
        self._refresh_btn = QPushButton(QIcon(os.path.join(_ICONS_DIR, "action_refresh.svg")), "Atualizar")
        self._refresh_btn.setIconSize(QSize(14, 14))
        self._refresh_btn.setFixedWidth(90)
        self._refresh_btn.clicked.connect(self._load_data)
        section_header.add_widget(self._refresh_btn)
        layout.addWidget(section_header)

        # Filtros textuais (ID, autor, descrição)
        filter_row1 = QHBoxLayout()
        filter_row1.setSpacing(4)

        self._filter_id = QLineEdit()
        self._filter_id.setPlaceholderText("ID")
        self._filter_id.setFixedWidth(60)
        self._filter_id.setClearButtonEnabled(True)
        self._filter_id.textChanged.connect(self._on_text_filter_changed)
        filter_row1.addWidget(self._filter_id)

        self._filter_author = QLineEdit()
        self._filter_author.setPlaceholderText("Autor...")
        self._filter_author.setClearButtonEnabled(True)
        self._filter_author.textChanged.connect(self._on_text_filter_changed)
        filter_row1.addWidget(self._filter_author, 1)

        self._filter_descricao = QLineEdit()
        self._filter_descricao.setPlaceholderText("Descrição...")
        self._filter_descricao.setClearButtonEnabled(True)
        self._filter_descricao.textChanged.connect(self._on_text_filter_changed)
        filter_row1.addWidget(self._filter_descricao, 2)

        layout.addLayout(filter_row1)

        # Filtro de status
        filter_row2 = QHBoxLayout()
        filter_row2.setSpacing(4)

        self._status_filter = QComboBox()
        for label in _STATUS_FILTERS:
            self._status_filter.addItem(label)
        self._status_filter.setCurrentIndex(0)
        self._status_filter.currentIndexChanged.connect(self._on_filter_changed)
        filter_row2.addWidget(self._status_filter, 1)

        layout.addLayout(filter_row2)

        # Ordenação
        sort_row = QHBoxLayout()
        sort_row.setSpacing(4)

        sort_label = QLabel("Ordenar:")
        sort_label.setStyleSheet("font-size: 11px; color: #757575;")
        sort_row.addWidget(sort_label)

        self._sort_combo = QComboBox()
        for label, _field in _SORT_OPTIONS:
            self._sort_combo.addItem(label)
        self._sort_combo.setCurrentIndex(0)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort_combo, 1)

        self._icon_sort_asc = QIcon(os.path.join(_ICONS_DIR, "sort_asc.svg"))
        self._icon_sort_desc = QIcon(os.path.join(_ICONS_DIR, "sort_desc.svg"))
        self._sort_toggle = QToolButton()
        self._sort_toggle.setIcon(self._icon_sort_asc)
        self._sort_toggle.setIconSize(QSize(18, 18))
        self._sort_toggle.setFixedSize(28, 28)
        self._sort_toggle.setToolTip("Alternar ascendente/descendente")
        self._sort_toggle.setCheckable(True)
        self._sort_toggle.toggled.connect(self._on_sort_toggled)
        sort_row.addWidget(self._sort_toggle)

        layout.addLayout(sort_row)

        # Lista de cards
        self._card_list = QListWidget()
        self._card_list.setSelectionMode(QListWidget.NoSelection)
        self._card_list.setFocusPolicy(Qt.NoFocus)
        self._card_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._card_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self._card_list.setSpacing(4)
        self._card_list.setStyleSheet(
            "QListWidget { border: none; background: transparent; }"
            "QListWidget::item { border: none; background: transparent; }"
        )
        layout.addWidget(self._card_list, 1)

        # Paginação
        pag = QHBoxLayout()
        pag.setContentsMargins(0, 2, 0, 0)
        pag.setSpacing(4)

        self._btn_prev = QPushButton()
        self._btn_prev.setIcon(QIcon(os.path.join(_ICONS_DIR, "pagination_prev.svg")))
        self._btn_prev.setFixedWidth(32)
        self._btn_prev.clicked.connect(self._on_prev_page)
        pag.addWidget(self._btn_prev)

        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setStyleSheet("font-size: 11px;")
        pag.addWidget(self._page_label, 1)

        self._btn_next = QPushButton()
        self._btn_next.setIcon(QIcon(os.path.join(_ICONS_DIR, "pagination_next.svg")))
        self._btn_next.setFixedWidth(32)
        self._btn_next.clicked.connect(self._on_next_page)
        pag.addWidget(self._btn_next)

        layout.addLayout(pag)

        # Status label
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("font-size: 11px; color: #757575;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self.setLayout(layout)

    # ================================================================
    # Card factory
    # ================================================================

    def _create_card(self, item):
        """Cria widget de card para um CatalogoItem de homologação."""
        card = QWidget()
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            "QWidget#satirriga_card { border: 1px solid palette(mid); border-radius: 6px;"
            " padding: 6px; background: palette(base); }"
        )
        card.setObjectName("satirriga_card")

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 40))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # --- Linha 1: #ID + status badge ---
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        id_label = QLabel(f"<b>#{item.mapeamento_id or 0}</b>")
        id_label.setStyleSheet("font-size: 13px;")
        row1.addWidget(id_label)

        status_text = item.status
        status_color = "#9E9E9E"
        try:
            status_enum = ZonalStatusEnum(item.status)
            status_text = status_enum.label
            status_color = status_enum.color
        except ValueError:
            pass

        badge = QLabel(status_text)
        badge.setStyleSheet(
            f"background-color: {status_color}; color: white;"
            " border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
        )
        badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row1.addWidget(badge)

        row1.addStretch()
        layout.addLayout(row1)

        # --- Linha 2: data + método + máscara ---
        data_ref = "—"
        if item.data_referencia:
            try:
                dt = datetime.fromisoformat(
                    item.data_referencia.replace("Z", "+00:00")
                )
                data_ref = dt.strftime("%d/%m/%Y")
            except (ValueError, AttributeError):
                data_ref = item.data_referencia[:10]

        metodo_label = self._format_metodo(item.metodo_apply) if item.metodo_apply else "—"
        meta_parts = [data_ref, metodo_label]
        if item.mascara_nome:
            meta_parts.append(item.mascara_nome)
        meta = QLabel("  ·  ".join(meta_parts))
        meta.setStyleSheet("font-size: 11px; color: #757575;")
        layout.addWidget(meta)

        # --- Linha 2b: data de edição ---
        if item.processed_at:
            try:
                dt_edit = datetime.fromisoformat(
                    item.processed_at.replace("Z", "+00:00")
                )
                edit_date = dt_edit.strftime("%d/%m/%Y")
            except (ValueError, AttributeError):
                edit_date = str(item.processed_at)[:10]
            edit_label = QLabel(f"Editado em: {edit_date}")
            edit_label.setStyleSheet("font-size: 10px; color: #757575;")
            layout.addWidget(edit_label)

        # --- Linha 2c: dados de homologação (quando HOMOLOGADO) ---
        if item.status == "HOMOLOGADO" and item.homologado_at:
            try:
                dt_hom = datetime.fromisoformat(
                    item.homologado_at.replace("Z", "+00:00")
                )
                hom_date = dt_hom.strftime("%d/%m/%Y")
            except (ValueError, AttributeError):
                hom_date = str(item.homologado_at)[:10]
            hom_text = f"Homologado em: {hom_date}"
            if item.homologador_nome:
                hom_text += f" por {item.homologador_nome}"
            hom_label = QLabel(hom_text)
            hom_label.setStyleSheet("font-size: 10px; color: #2E7D32;")
            layout.addWidget(hom_label)

        # --- Linha 3: descrição HTML (máximo 3 linhas) ---
        desc_label = QLabel()
        desc_label.setTextFormat(Qt.RichText)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 11px; padding: 0;")
        line_height = QFontMetrics(desc_label.font()).lineSpacing()
        desc_label.setMaximumHeight(line_height * 3 + 4)

        plain = ""
        if item.descricao:
            doc = QTextDocument()
            doc.setHtml(item.descricao)
            plain = doc.toPlainText().strip()

        if plain:
            fm = QFontMetrics(desc_label.font())
            max_width = 400
            lines = plain.split("\n")
            displayed = []
            for line in lines:
                if len(displayed) >= 3:
                    break
                elided = fm.elidedText(line, Qt.ElideRight, max_width)
                displayed.append(elided)
            desc_label.setText("<br>".join(displayed))
            desc_label.setToolTip(plain)
        else:
            desc_label.setText("<i style='color:#9E9E9E'>Sem descrição</i>")

        layout.addWidget(desc_label)

        # --- Linha 4: autor + features/área ---
        row4 = QHBoxLayout()
        row4.setSpacing(6)

        author = QLabel(f"Autor: {item.author or '—'}")
        author.setStyleSheet("font-size: 11px; color: #757575;")
        row4.addWidget(author)

        row4.addStretch()

        feat_area = f"{item.result_count or 0} feições  ·  {(item.total_area_ha or 0):,.1f} ha"
        stats = QLabel(feat_area)
        stats.setStyleSheet("font-size: 11px; color: #757575;")
        row4.addWidget(stats)

        layout.addLayout(row4)

        # --- Linha 5: ações de homologação ---
        if item.status == "AGUARDANDO":
            row_actions = QHBoxLayout()
            row_actions.setSpacing(4)
            row_actions.addStretch()

            btn_aprovar = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_check.svg"), "#FFFFFF"), "Aprovar")
            btn_aprovar.setIconSize(QSize(14, 14))
            btn_aprovar.setStyleSheet(
                "QPushButton { background-color: #2E7D32; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #1B5E20; }"
            )
            btn_aprovar.clicked.connect(
                lambda _, zid=item.id: self._on_parecer(zid)
            )
            row_actions.addWidget(btn_aprovar)

            btn_devolver = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_undo.svg"), "#FFFFFF"), "Devolver")
            btn_devolver.setIconSize(QSize(14, 14))
            btn_devolver.setToolTip("Devolver para edição — retorna ao editor com orientações")
            btn_devolver.setStyleSheet(
                "QPushButton { background-color: #1565C0; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #0D47A1; }"
            )
            btn_devolver.clicked.connect(
                lambda _, zid=item.id: self._on_devolver(zid)
            )
            row_actions.addWidget(btn_devolver)

            btn_reprovar = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_x.svg"), "#FFFFFF"), "Reprovar")
            btn_reprovar.setIconSize(QSize(14, 14))
            btn_reprovar.setStyleSheet(
                "QPushButton { background-color: #C62828; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #B71C1C; }"
            )
            btn_reprovar.clicked.connect(
                lambda _, zid=item.id: self._on_parecer(zid)
            )
            row_actions.addWidget(btn_reprovar)

            layout.addLayout(row_actions)

        # --- Linha 6: ações secundárias (Baixar, Retirar, Excluir) ---
        row_secondary = QHBoxLayout()
        row_secondary.setSpacing(4)
        row_secondary.addStretch()

        btn_download = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_download.svg"), "#FFFFFF"), "Baixar")
        btn_download.setIconSize(QSize(14, 14))
        btn_download.setToolTip("Baixar resultado zonal como GeoPackage editável")
        btn_download.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white;"
            " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1565C0; }"
            "QPushButton:disabled { background-color: #90CAF9; }"
        )
        btn_download.clicked.connect(
            lambda _, zid=item.id, ci=item: self._on_download(zid, ci)
        )
        row_secondary.addWidget(btn_download)

        if item.status == "HOMOLOGADO":
            btn_retirar = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_rotate_ccw.svg"), "#FFFFFF"), "Retirar")
            btn_retirar.setIconSize(QSize(14, 14))
            btn_retirar.setToolTip("Retirar homologação — reverte para reanálise")
            btn_retirar.setStyleSheet(
                "QPushButton { background-color: #E65100; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #BF360C; }"
            )
            btn_retirar.clicked.connect(
                lambda _, zid=item.id: self._on_retirar(zid)
            )
            row_secondary.addWidget(btn_retirar)

        if item.mapeamento_id:
            btn_suprimir = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_trash.svg"), "#FFFFFF"), "Excluir")
            btn_suprimir.setIconSize(QSize(14, 14))
            btn_suprimir.setToolTip("Excluir mapeamento definitivamente")
            btn_suprimir.setStyleSheet(
                "QPushButton { background-color: #7B1FA2; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #4A148C; }"
            )
            btn_suprimir.clicked.connect(
                lambda _, mid=item.mapeamento_id: self._on_suprimir(mid)
            )
            row_secondary.addWidget(btn_suprimir)

        layout.addLayout(row_secondary)

        card.setLayout(layout)
        card._download_btn = btn_download
        card._zonal_id = item.id
        return card

    # ================================================================
    # Signals / slots
    # ================================================================

    def _connect_signals(self):
        self._state.loading_changed.connect(self._on_loading_changed)
        self._state.error_occurred.connect(self._on_error)
        self._state.auth_state_changed.connect(self._on_auth_changed)
        self._state.catalogo_homologacao_changed.connect(self._on_data_loaded)
        self._state.parecer_emitido.connect(self._on_parecer_emitido)
        self._state.mapeamento_suprimido.connect(self._on_mapeamento_suprimido)

    def _on_auth_changed(self, is_authenticated):
        if is_authenticated:
            self._load_data()
        else:
            self._card_list.clear()

    def _on_text_filter_changed(self, _text):
        """Debounce nos filtros textuais — reseta para página 1."""
        self._current_page = 1
        self._search_timer.start(400)

    def _on_filter_changed(self, _index):
        self._current_page = 1
        self._load_data()

    def _on_sort_changed(self, _index):
        self._current_page = 1
        self._load_data()

    def _on_sort_toggled(self, checked):
        self._sort_toggle.setIcon(self._icon_sort_desc if checked else self._icon_sort_asc)
        self._current_page = 1
        self._load_data()

    def _load_data(self):
        """Carrega catálogo de homologação com filtros, ordenação e paginação."""
        filter_text = self._status_filter.currentText()
        status = _STATUS_FILTERS.get(filter_text, "AGUARDANDO")
        sort_index = self._sort_combo.currentIndex()
        sort_field = _SORT_OPTIONS[sort_index][1]
        sort_direction = "desc" if self._sort_toggle.isChecked() else "asc"
        self._controller.load_catalogo_homologacao(
            status_filter=status,
            mapeamento_id=self._filter_id.text().strip(),
            author=self._filter_author.text().strip(),
            descricao=self._filter_descricao.text().strip(),
            page=self._current_page,
            size=20,
            sort=sort_field,
            direction=sort_direction,
        )

    def _on_data_loaded(self, items, pagination):
        """Atualiza cards com itens recebidos."""
        self._items = items
        self._current_page = pagination.get("page", 1)
        self._total_pages = pagination.get("totalPages", 1)
        self._total_items = pagination.get("total", len(items))
        self._card_list.clear()

        if not items:
            self._status_label.setText("Nenhum mapeamento encontrado")
            self._status_label.setVisible(True)
            return

        self._status_label.setVisible(False)

        for item in items:
            card = self._create_card(item)
            list_item = QListWidgetItem(self._card_list)
            list_item.setSizeHint(card.sizeHint() + QSize(0, 8))
            self._card_list.addItem(list_item)
            self._card_list.setItemWidget(list_item, card)

        self._update_pagination()

    # ================================================================
    # Paginação
    # ================================================================

    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._load_data()

    def _on_next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._load_data()

    def _update_pagination(self):
        total = self._total_items
        suffix = "registro" if total == 1 else "registros"
        self._page_label.setText(
            f"Página {self._current_page} de {self._total_pages}  ({total} {suffix})"
        )
        self._btn_prev.setEnabled(self._current_page > 1)
        self._btn_next.setEnabled(self._current_page < self._total_pages)

    # ================================================================
    # Actions
    # ================================================================

    def _on_download(self, zonal_id, catalogo_item):
        # Homologador visualiza sem bloquear edição — sempre read_only
        self._controller.download_zonal_result(
            zonal_id, catalogo_item=catalogo_item, read_only=True,
        )

    def _on_parecer(self, zonal_id):
        from ..dialogs.parecer_dialog import ParecerDialog

        dialog = ParecerDialog(zonal_id, parent=self)
        if dialog.exec_() == ParecerDialog.Accepted:
            result = dialog.get_result()
            if result:
                decisao, motivo = result
                self._controller.emitir_parecer(zonal_id, decisao, motivo)

    def _on_devolver(self, zonal_id):
        """Devolver para edição — parecer DEVOLVIDO com orientação ao editor."""
        motivo, ok = self._ask_motivo(
            "Devolver para edição",
            "Orientação ao editor (mínimo 10 caracteres):",
            min_chars=10,
        )
        if ok and motivo:
            self._controller.emitir_parecer(zonal_id, "DEVOLVIDO", motivo)

    def _on_retirar(self, zonal_id):
        """Retirar homologação — submete parecer CANCELADO para zonal HOMOLOGADO."""
        motivo, ok = self._ask_motivo(
            "Retirar homologação",
            "Motivo da retirada (mínimo 20 caracteres):",
            min_chars=20,
        )
        if ok and motivo:
            self._controller.emitir_parecer(zonal_id, "CANCELADO", motivo)

    def _ask_motivo(self, title, prompt, min_chars=10):
        """Solicita motivo ao usuário com validação de tamanho mínimo."""
        from qgis.PyQt.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(self, title, prompt)
        if ok and len(text.strip()) < min_chars:
            QMessageBox.warning(
                self, title,
                f"O texto deve ter no mínimo {min_chars} caracteres.",
            )
            return "", False
        return text.strip(), ok

    def _on_suprimir(self, mapeamento_id):
        """Suprime mapeamento — exclusão definitiva (soft delete)."""
        reply = QMessageBox.warning(
            self,
            "Suprimir mapeamento",
            f"Esta ação suprimirá permanentemente o mapeamento #{mapeamento_id} "
            "e todos os seus dados associados.\n\n"
            "Esta operação é irreversível. Deseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._controller.suprimir_mapeamento(mapeamento_id)

    def _on_parecer_emitido(self, data):
        self._load_data()

    def _on_mapeamento_suprimido(self, data):
        self._load_data()

    # ================================================================
    # Loading / Error
    # ================================================================

    def _on_loading_changed(self, operation, is_loading):
        if operation == "catalogo_homologacao":
            self._refresh_btn.setEnabled(not is_loading)
            if is_loading:
                self._status_label.setText("Carregando...")
                self._status_label.setStyleSheet("font-size: 11px;")
                self._status_label.setVisible(True)
            else:
                self._status_label.setVisible(False)
        elif operation.startswith("download:"):
            target_zonal_id = int(operation.split(":", 1)[1])
            for row in range(self._card_list.count()):
                widget = self._card_list.itemWidget(self._card_list.item(row))
                if widget and hasattr(widget, "_zonal_id") and widget._zonal_id == target_zonal_id:
                    widget._download_btn.setEnabled(not is_loading)
                    break

    def _on_error(self, operation, message):
        if operation in ("catalogo_homologacao", "parecer"):
            self._status_label.setText(f"Erro: {message}")
            self._status_label.setStyleSheet("color: #F44336; font-size: 11px;")
            self._status_label.setVisible(True)

    @staticmethod
    def _format_metodo(metodo_apply):
        """Converte metodoApply em label legível."""
        labels = {
            "METODO_1": "Fatiamento do índice de Vegetação",
            "METODO_2_DISCRETO": "Detecção de mudança (discreto)",
            "METODO_2_FUZZY": "Detecção de mudança (fuzzy)",
            "METODO_3": "Método 3",
            "AUTOMATICO": "Automático",
        }
        return labels.get(metodo_apply, metodo_apply)
