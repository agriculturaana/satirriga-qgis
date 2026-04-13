"""Aba de catálogo zonal — cards de mapeamentos disponíveis para edição."""

import os
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QSize, QTimer
from qgis.PyQt.QtGui import QColor, QIcon, QTextDocument, QFontMetrics
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QComboBox, QListWidget, QListWidgetItem,
    QFrame, QSizePolicy, QGraphicsDropShadowEffect, QToolButton,
)

from qgis.core import QgsMessageLog, Qgis

from ..theme import SectionHeader
from ..icon_utils import tinted_icon

from ...domain.models.enums import ZonalStatusEnum

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)
from ...infra.config.settings import PLUGIN_NAME

# Itens por página padrão (server-side)
_PAGE_SIZE = 5

# Opções de ordenação: label exibido → campo da API
_SORT_OPTIONS = [
    ("#ID", "mapeamentoId"),
    ("Data", "dataReferencia"),
    ("Autor", "author"),
    ("Descrição", "descricao"),
]

# Debounce para busca textual (ms)
_SEARCH_DEBOUNCE_MS = 400


class MapeamentosTab(QWidget):
    """Catálogo de zonais disponíveis — layout em cards com filtros e paginação server-side."""

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller

        # Estado de paginação server-side
        self._current_page = 1
        self._total_pages = 1
        self._total_items = 0

        # Tracking de widgets dinâmicos nos cards
        self._progress_labels = {}     # zonal_id -> QLabel
        self._encerrar_buttons = {}    # zonal_id -> QPushButton

        # Debounce timer para busca textual
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._on_search_debounced)

        self._build_ui()
        self._connect_signals()

        if self._state.is_authenticated:
            self._request_page()
            self._controller.load_notifications()

    # ================================================================
    # UI construction
    # ================================================================

    def _build_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # --- Header ---
        section_header = SectionHeader("Mapeamentos", "disponíveis para edição")
        self._refresh_btn = QPushButton(QIcon(os.path.join(_ICONS_DIR, "action_refresh.svg")), "Atualizar")
        self._refresh_btn.setIconSize(QSize(14, 14))
        self._refresh_btn.setFixedWidth(90)
        self._refresh_btn.setToolTip("Atualizar lista de mapeamentos disponíveis")
        self._refresh_btn.clicked.connect(self._on_catalogo_refresh)
        section_header.add_widget(self._refresh_btn)
        root.addWidget(section_header)

        # --- Notificações (pareceres) ---
        self._notif_container = QWidget()
        self._notif_layout = QVBoxLayout()
        self._notif_layout.setContentsMargins(0, 0, 0, 0)
        self._notif_layout.setSpacing(2)
        self._notif_container.setLayout(self._notif_layout)
        self._notif_container.setVisible(False)
        root.addWidget(self._notif_container)

        # --- Filtros ---
        root.addWidget(self._build_filters())

        # --- Lista de cards ---
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
        root.addWidget(self._card_list, 1)

        # --- Paginação ---
        root.addWidget(self._build_pagination())

        # --- Status label ---
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("font-size: 11px; color: #757575;")
        self._status_label.setVisible(False)
        root.addWidget(self._status_label)

        self.setLayout(root)

    def _build_filters(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Linha 1: filtros textuais (ID, autor, descrição)
        row1 = QHBoxLayout()
        row1.setSpacing(4)

        self._filter_id = QLineEdit()
        self._filter_id.setPlaceholderText("ID")
        self._filter_id.setFixedWidth(60)
        self._filter_id.setClearButtonEnabled(True)
        self._filter_id.textChanged.connect(self._on_search_text_changed)
        row1.addWidget(self._filter_id)

        self._filter_author = QLineEdit()
        self._filter_author.setPlaceholderText("Autor...")
        self._filter_author.setClearButtonEnabled(True)
        self._filter_author.textChanged.connect(self._on_search_text_changed)
        row1.addWidget(self._filter_author, 1)

        self._filter_descricao = QLineEdit()
        self._filter_descricao.setPlaceholderText("Descrição...")
        self._filter_descricao.setClearButtonEnabled(True)
        self._filter_descricao.textChanged.connect(self._on_search_text_changed)
        row1.addWidget(self._filter_descricao, 2)

        outer.addLayout(row1)

        # Linha 2: filtros de seleção (status, método)
        row2 = QHBoxLayout()
        row2.setSpacing(4)

        self._filter_status = QComboBox()
        self._filter_status.addItem("Todos os status", "")
        _ALLOWED_STATUSES = {
            ZonalStatusEnum.CONSOLIDATED,
            ZonalStatusEnum.CONSOLIDATION_FAILED,
            ZonalStatusEnum.OVERLAID,
            ZonalStatusEnum.INVALIDATED,
            ZonalStatusEnum.HOMOLOGADO,
            ZonalStatusEnum.REPROVADO,
            ZonalStatusEnum.CANCELADO,
        }
        for s in ZonalStatusEnum:
            if s in _ALLOWED_STATUSES:
                self._filter_status.addItem(s.label, s.value)
        idx = self._filter_status.findData(ZonalStatusEnum.CONSOLIDATED.value)
        if idx >= 0:
            self._filter_status.setCurrentIndex(idx)
        self._filter_status.currentIndexChanged.connect(self._on_filter_combo_changed)
        row2.addWidget(self._filter_status, 1)

        self._filter_metodo = QComboBox()
        self._filter_metodo.addItem("Todos os métodos", "")
        for key, label in [
            ("METODO_1", "Método 1"),
            ("METODO_2_DISCRETO", "Método 2a (Discreto)"),
            ("METODO_2_FUZZY", "Método 2b (Fuzzy)"),
            ("METODO_3", "Método 3"),
        ]:
            self._filter_metodo.addItem(label, key)
        self._filter_metodo.currentIndexChanged.connect(self._on_filter_combo_changed)
        row2.addWidget(self._filter_metodo, 1)

        outer.addLayout(row2)

        # Linha 3: ordenação
        row3 = QHBoxLayout()
        row3.setSpacing(4)

        sort_label = QLabel("Ordenar:")
        sort_label.setStyleSheet("font-size: 11px; color: #757575;")
        row3.addWidget(sort_label)

        self._sort_combo = QComboBox()
        for label, _field in _SORT_OPTIONS:
            self._sort_combo.addItem(label)
        self._sort_combo.setCurrentIndex(0)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        row3.addWidget(self._sort_combo, 1)

        self._icon_sort_asc = QIcon(os.path.join(_ICONS_DIR, "sort_asc.svg"))
        self._icon_sort_desc = QIcon(os.path.join(_ICONS_DIR, "sort_desc.svg"))
        self._sort_toggle = QToolButton()
        self._sort_toggle.setIcon(self._icon_sort_asc)
        self._sort_toggle.setIconSize(QSize(18, 18))
        self._sort_toggle.setFixedSize(28, 28)
        self._sort_toggle.setToolTip("Alternar ascendente/descendente")
        self._sort_toggle.setCheckable(True)
        self._sort_toggle.toggled.connect(self._on_sort_toggled)
        row3.addWidget(self._sort_toggle)

        outer.addLayout(row3)

        frame.setLayout(outer)
        return frame

    def _build_pagination(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(4)

        self._btn_prev = QPushButton()
        self._btn_prev.setIcon(QIcon(os.path.join(_ICONS_DIR, "pagination_prev.svg")))
        self._btn_prev.setFixedWidth(32)
        self._btn_prev.setToolTip("Página anterior")
        self._btn_prev.clicked.connect(self._on_prev_page)
        layout.addWidget(self._btn_prev)

        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._page_label, 1)

        self._btn_next = QPushButton()
        self._btn_next.setIcon(QIcon(os.path.join(_ICONS_DIR, "pagination_next.svg")))
        self._btn_next.setFixedWidth(32)
        self._btn_next.setToolTip("Próxima página")
        self._btn_next.clicked.connect(self._on_next_page)
        layout.addWidget(self._btn_next)

        frame.setLayout(layout)
        return frame

    # ================================================================
    # Card widget factory
    # ================================================================

    def _create_card(self, item):
        """Cria widget de card para um CatalogoItem."""
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

        # --- Linha 1: #ID + status badge + botão baixar ---
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        id_label = QLabel(f"<b>#{item.mapeamento_id or 0}</b>")
        id_label.setStyleSheet("font-size: 13px;")
        row1.addWidget(id_label)

        # Status badge
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

        # --- Ações condicionais por status (mutuamente exclusivas) ---

        _reprocessable = {
            ZonalStatusEnum.FAILED.value,
            ZonalStatusEnum.CONSOLIDATION_FAILED.value,
        }
        _intermediate = {"PROCESSING", "OVERLAID", "CREATED", "CONSOLIDATING"}
        _parecer_statuses = {
            ZonalStatusEnum.HOMOLOGADO.value,
            ZonalStatusEnum.REPROVADO.value,
            ZonalStatusEnum.CANCELADO.value,
        }

        is_polling = self._controller.is_polling(item.id)

        if item.status in _reprocessable and not is_polling:
            # Botão Reprocessar
            btn_reprocess = QPushButton(
                tinted_icon(os.path.join(_ICONS_DIR, "action_rotate_cw.svg"), "#FFFFFF"),
                "Reprocessar",
            )
            btn_reprocess.setIconSize(QSize(14, 14))
            btn_reprocess.setToolTip("Reenviar para processamento de overlay")
            btn_reprocess.setStyleSheet(
                "QPushButton { background-color: #FF9800; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #F57C00; }"
            )
            btn_reprocess.clicked.connect(
                lambda _, zid=item.id: self._reprocess_overlay(zid)
            )
            row1.addWidget(btn_reprocess)

        elif item.status in _intermediate or is_polling:
            # Label de progresso inline
            progress_text = self._progress_text_for_status(item.status)
            lbl_progress = QLabel(progress_text)
            lbl_progress.setStyleSheet(
                "font-size: 10px; font-style: italic; color: #FF9800;"
                " padding: 2px 6px;"
            )
            row1.addWidget(lbl_progress)
            self._progress_labels[item.id] = lbl_progress

        elif item.status == ZonalStatusEnum.CONSOLIDATED.value:
            # Botão Encerrar para Homologação
            btn_encerrar = QPushButton(
                tinted_icon(os.path.join(_ICONS_DIR, "action_check.svg"), "#FFFFFF"),
                "Encerrar",
            )
            btn_encerrar.setIconSize(QSize(14, 14))
            btn_encerrar.setToolTip("Enviar para homologação")
            btn_encerrar.setStyleSheet(
                "QPushButton { background-color: #2E7D32; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #1B5E20; }"
                "QPushButton:disabled { background-color: #A5D6A7; color: #E8F5E9; }"
            )
            btn_encerrar.clicked.connect(
                lambda _, zid=item.id: self._finalizar_zonal(zid)
            )
            row1.addWidget(btn_encerrar)
            self._encerrar_buttons[item.id] = btn_encerrar

        elif item.status in _parecer_statuses and item.mapeamento_id:
            # Botão Ver Parecer
            btn_parecer = QPushButton(
                tinted_icon(os.path.join(_ICONS_DIR, "action_info.svg"), "#FFFFFF"),
                "Parecer",
            )
            btn_parecer.setIconSize(QSize(14, 14))
            btn_parecer.setToolTip("Visualizar pareceres deste mapeamento")
            btn_parecer.setStyleSheet(
                "QPushButton { background-color: #7B1FA2; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #6A1B9A; }"
            )
            btn_parecer.clicked.connect(
                lambda _, mid=item.mapeamento_id: self._on_view_parecer(mid)
            )
            row1.addWidget(btn_parecer)

        btn = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_download.svg"), "#FFFFFF"), "Baixar")
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip("Baixar resultado zonal como GeoPackage editável")
        btn.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white;"
            " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1565C0; }"
            "QPushButton:disabled { background-color: #90CAF9; }"
        )

        # Desabilitar download para status não-baixáveis
        _downloadable = {
            ZonalStatusEnum.CONSOLIDATED.value,
            ZonalStatusEnum.DONE.value,
            ZonalStatusEnum.AGUARDANDO.value,
            ZonalStatusEnum.HOMOLOGADO.value,
            ZonalStatusEnum.REPROVADO.value,
        }
        if item.status not in _downloadable:
            btn.setEnabled(False)
            btn.setToolTip(f"Download indisponível (status: {status_text})")

        row1.addWidget(btn)

        layout.addLayout(row1)

        # --- Linha 2: data + método ---
        row2 = QHBoxLayout()
        row2.setSpacing(6)

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
        meta = QLabel(f"{data_ref}  ·  {metodo_label}")
        meta.setStyleSheet("font-size: 11px; color: #757575;")
        row2.addWidget(meta)
        row2.addStretch()

        layout.addLayout(row2)

        # --- Linha 3: descrição HTML (máximo 3 linhas) ---
        desc_label = QLabel()
        desc_label.setTextFormat(Qt.RichText)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 11px; padding: 0;")
        line_height = QFontMetrics(desc_label.font()).lineSpacing()
        desc_label.setMaximumHeight(line_height * 3 + 4)

        # Extrair texto puro do HTML e limitar a 3 linhas
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
            if len(lines) > 3:
                displayed[-1] = fm.elidedText(lines[2], Qt.ElideRight, max_width)
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

        # --- Linha 5: sinc. local + tamanho GPKG ---
        from ...domain.services.gpkg_service import gpkg_path_for_zonal, read_sidecar
        try:
            base = self._controller.get_gpkg_base_dir()
            gpkg = gpkg_path_for_zonal(base, item.id)
            row5 = QHBoxLayout()
            row5.setSpacing(6)

            if os.path.isfile(gpkg):
                sidecar = read_sidecar(gpkg)
                sinc_status = "Baixado"
                sinc_color = "#2E7D32"
                if sidecar.get("editToken"):
                    sinc_status = "Em edição"
                    sinc_color = "#1565C0"
                size_bytes = os.path.getsize(gpkg)
                if size_bytes > 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / 1024:.0f} KB"
                sinc_label = QLabel(f"<b style='color:{sinc_color}'>{sinc_status}</b>  ·  {size_str}")
            else:
                sinc_label = QLabel("<span style='color:#9E9E9E'>Não baixado</span>")
            sinc_label.setStyleSheet("font-size: 10px;")
            sinc_label.setTextFormat(Qt.RichText)
            row5.addWidget(sinc_label)
            row5.addStretch()

            layout.addLayout(row5)
        except Exception:
            pass

        card.setLayout(layout)
        card._download_btn = btn
        card._zonal_id = item.id
        return card

    # ================================================================
    # Signals / slots
    # ================================================================

    def _connect_signals(self):
        self._state.loading_changed.connect(self._on_loading_changed)
        self._state.error_occurred.connect(self._on_error)
        self._state.auth_state_changed.connect(self._on_auth_changed)
        self._state.catalogo_changed.connect(self._on_catalogo_changed)
        self._state.reprocess_overlay_done.connect(self._on_reprocess_done)
        self._state.zonal_status_polled.connect(self._on_zonal_status_polled)
        self._state.zonal_finalizado.connect(self._on_zonal_finalizado)
        self._controller.notifications_loaded.connect(self._on_notifications_loaded)
        self._controller.pareceres_loaded.connect(self._on_pareceres_loaded)

    def _on_catalogo_refresh(self):
        self._request_page()
        self._controller.load_notifications()

    def _on_auth_changed(self, is_authenticated):
        if is_authenticated:
            self._current_page = 1
            self._request_page()
            self._controller.load_notifications()
        else:
            self._card_list.clear()
            self._update_pagination_controls()

    # ================================================================
    # Server-side request
    # ================================================================

    def _request_page(self):
        """Dispara requisição ao servidor com filtros, ordenação e página corrente."""
        status = self._filter_status.currentData() or "CONSOLIDATED"
        metodo = self._filter_metodo.currentData() or ""
        mapeamento_id = self._filter_id.text().strip()
        author = self._filter_author.text().strip()
        descricao = self._filter_descricao.text().strip()

        sort_index = self._sort_combo.currentIndex()
        sort_field = _SORT_OPTIONS[sort_index][1]
        sort_direction = "desc" if self._sort_toggle.isChecked() else "asc"

        # Homologadores veem consolidados de todos; demais veem apenas os próprios
        is_homologador = (
            getattr(self._state.user, "is_homologador", False)
            if self._state.user else False
        )
        if not is_homologador:
            if not author and self._state.user:
                author = self._state.user.name or ""

        self._controller.load_catalogo(
            page=self._current_page,
            size=_PAGE_SIZE,
            status=status,
            metodo=metodo,
            mapeamento_id=mapeamento_id,
            author=author,
            descricao=descricao,
            sort=sort_field,
            direction=sort_direction,
            only_mine=not is_homologador,
        )

    # ================================================================
    # Catálogo update (server response)
    # ================================================================

    def _on_catalogo_changed(self, items, pagination):
        """Recebe página de CatalogoItems + metadados de paginação."""
        self._progress_labels.clear()
        self._encerrar_buttons.clear()
        self._card_list.clear()

        # Atualizar estado de paginação
        self._current_page = pagination.get("page", 1)
        self._total_pages = pagination.get("totalPages", 1)
        self._total_items = pagination.get("total", len(items))

        if not items:
            self._status_label.setText("Nenhum mapeamento disponível")
            self._status_label.setStyleSheet("font-size: 11px; color: #757575;")
            self._status_label.setVisible(True)
        else:
            self._status_label.setVisible(False)

        for item in items:
            card = self._create_card(item)
            card._download_btn.clicked.connect(
                lambda checked, zid=item.id, ci=item: self._on_zonal_download_clicked(zid, ci)
            )
            list_item = QListWidgetItem(self._card_list)
            list_item.setSizeHint(card.sizeHint() + QSize(0, 8))
            self._card_list.addItem(list_item)
            self._card_list.setItemWidget(list_item, card)

        self._update_pagination_controls()

    # ================================================================
    # Filtros (disparam request server-side)
    # ================================================================

    def _on_search_text_changed(self, _text):
        """Debounce na busca textual para não sobrecarregar o servidor."""
        self._search_timer.start(_SEARCH_DEBOUNCE_MS)

    def _on_search_debounced(self):
        self._current_page = 1
        self._request_page()

    def _on_filter_combo_changed(self, _index):
        self._current_page = 1
        self._request_page()

    # ================================================================
    # Ordenação (server-side)
    # ================================================================

    def _on_sort_changed(self, _index):
        self._current_page = 1
        self._request_page()

    def _on_sort_toggled(self, checked):
        self._sort_toggle.setIcon(self._icon_sort_desc if checked else self._icon_sort_asc)
        self._current_page = 1
        self._request_page()

    # ================================================================
    # Paginação
    # ================================================================

    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._request_page()

    def _on_next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._request_page()

    def _update_pagination_controls(self):
        total = self._total_items
        suffix = "registro" if total == 1 else "registros"
        self._page_label.setText(
            f"Página {self._current_page} de {self._total_pages}  ({total} {suffix})"
        )
        self._btn_prev.setEnabled(self._current_page > 1)
        self._btn_next.setEnabled(self._current_page < self._total_pages)

    # ================================================================
    # Helpers
    # ================================================================

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

    def _on_notifications_loaded(self, notifications):
        """Exibe notificações de pareceres acima do catálogo."""
        # Limpa notificações anteriores
        while self._notif_layout.count():
            child = self._notif_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Filtra apenas não lidas
        unread = [n for n in notifications if not n.get("lida", True)]
        if not unread:
            self._notif_container.setVisible(False)
            return

        _NOTIF_STYLES = {
            "MAPEAMENTO_HOMOLOGADO": ("#E8F5E9", "#2E7D32", "Aprovado"),
            "MAPEAMENTO_REPROVADO": ("#FFEBEE", "#C62828", "Reprovado"),
            "MAPEAMENTO_DEVOLVIDO": ("#FFF3E0", "#E65100", "Devolvido"),
            "MAPEAMENTO_CANCELADO": ("#EFEBE9", "#4E342E", "Cancelado"),
        }

        for notif in unread[:5]:  # máximo 5 notificações visíveis
            tipo = notif.get("tipo", "")
            payload = notif.get("payload") or {}
            notif_id = notif.get("id")
            style = _NOTIF_STYLES.get(tipo, ("#E3F2FD", "#1565C0", tipo))

            mapeamento_id = payload.get("mapeamentoId", "?")
            revisor = payload.get("revisorNome", "")
            motivo = payload.get("motivo", "")
            decisao_label = style[2]

            text = f"<b>#{mapeamento_id} — {decisao_label}</b>"
            if revisor:
                text += f" por {revisor}"
            if motivo:
                text += f"<br/><i>{motivo[:120]}</i>"

            card = QWidget()
            card_layout = QHBoxLayout()
            card_layout.setContentsMargins(8, 4, 8, 4)

            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet(f"font-size: 11px; color: {style[1]}; border: none; background: transparent;")
            card_layout.addWidget(lbl, 1)

            btn_dismiss = QPushButton("✕")
            btn_dismiss.setFixedSize(20, 20)
            btn_dismiss.setToolTip("Marcar como lida")
            btn_dismiss.setStyleSheet(
                f"border: none; color: {style[1]}; font-size: 12px; font-weight: bold; background: transparent;"
            )
            btn_dismiss.clicked.connect(
                lambda _, nid=notif_id: self._dismiss_notification(nid)
            )
            card_layout.addWidget(btn_dismiss)

            card.setLayout(card_layout)
            card.setStyleSheet(
                f"background-color: {style[0]}; border-radius: 4px; "
                f"border-left: 3px solid {style[1]};"
            )
            self._notif_layout.addWidget(card)

        self._notif_container.setVisible(True)

    def _dismiss_notification(self, notif_id):
        """Marca notificação como lida e remove do painel."""
        if notif_id:
            self._controller.mark_notification_read(notif_id)
        # Recarrega notificações
        self._controller.load_notifications()

    def _on_zonal_download_clicked(self, zonal_id, catalogo_item=None):
        """Inicia download do resultado zonal.

        Status finais irreversíveis são baixados em modo somente leitura.
        REPROVADO permite edição (checkout) para correção pelo dono/homologador.
        """
        _READ_ONLY_STATUSES = {
            ZonalStatusEnum.AGUARDANDO.value,
            ZonalStatusEnum.HOMOLOGADO.value,
            ZonalStatusEnum.CANCELADO.value,
        }
        read_only = (
            catalogo_item is not None
            and catalogo_item.status in _READ_ONLY_STATUSES
        )
        self._controller.download_zonal_result(
            zonal_id, catalogo_item=catalogo_item, read_only=read_only,
        )

    def _reprocess_overlay(self, zonal_id):
        """Dispara reprocessamento de overlay para zonal com falha."""
        self._controller.reprocess_overlay(zonal_id)

    def _on_reprocess_done(self, zonal_id, message):
        """Callback após reprocessamento disparado — recarrega catálogo para mostrar progresso."""
        QgsMessageLog.logMessage(
            f"[Reprocess] Zonal #{zonal_id}: {message}", PLUGIN_NAME, Qgis.Info,
        )
        self._request_page()

    def _on_zonal_status_polled(self, zonal_id, status):
        """Atualiza label de progresso inline quando polling retorna novo status."""
        lbl = self._progress_labels.get(zonal_id)
        if lbl is not None:
            try:
                lbl.setText(self._progress_text_for_status(status))
            except RuntimeError:
                # Widget C++ já destruído
                self._progress_labels.pop(zonal_id, None)
                return

        # Status terminal: refresh para recriar card com widget correto
        _intermediate = {"PROCESSING", "OVERLAID", "CREATED", "CONSOLIDATING"}
        if status not in _intermediate:
            self._request_page()

    def _on_zonal_finalizado(self, zonal_id, new_status):
        """Callback após finalizar zonal para homologação."""
        from qgis.PyQt.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "Mapeamento encerrado",
            f"Zonal #{zonal_id} encerrado para homologação.\n"
            f"Novo status: {new_status}",
        )
        self._request_page()

    def _finalizar_zonal(self, zonal_id):
        """Envia zonal para homologação."""
        self._controller.finalizar_zonal(zonal_id)

    @staticmethod
    def _progress_text_for_status(status):
        """Retorna texto de progresso para exibição inline."""
        _texts = {
            "PROCESSING": "Processando overlay...",
            "OVERLAID": "Recalculando estatísticas...",
            "CONSOLIDATING": "Consolidando...",
            "CREATED": "Aguardando processamento...",
        }
        return _texts.get(status, "Processando...")

    def _on_view_parecer(self, mapeamento_id):
        """Solicita histórico de pareceres ao servidor."""
        self._controller.load_pareceres(mapeamento_id)

    def _on_pareceres_loaded(self, mapeamento_id, pareceres):
        """Exibe dialog com histórico de pareceres."""
        from ..dialogs.parecer_detail_dialog import ParecerDetailDialog
        dialog = ParecerDetailDialog(mapeamento_id, pareceres, parent=self)
        dialog.exec_()

    # ================================================================
    # Loading / Error
    # ================================================================

    def _on_loading_changed(self, operation, is_loading):
        if operation.startswith("download:"):
            target_zonal_id = int(operation.split(":", 1)[1])
            for row in range(self._card_list.count()):
                widget = self._card_list.itemWidget(self._card_list.item(row))
                if widget and hasattr(widget, "_zonal_id") and widget._zonal_id == target_zonal_id:
                    widget._download_btn.setEnabled(not is_loading)
                    widget._download_btn.setText("Baixando..." if is_loading else "Baixar")
                    break
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
        elif operation == "reprocess":
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Erro ao reprocessar",
                f"Não foi possível iniciar o reprocessamento:\n\n{message}",
            )
        elif operation == "finalizar_zonal":
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Erro ao encerrar",
                f"Não foi possível encerrar o zonal:\n\n{message}",
            )
