"""Aba de camadas locais — cards de GPKGs V2, sync status, ações."""

import os
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor, QFontMetrics, QIcon, QTextDocument
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QSizePolicy, QMessageBox,
    QGraphicsDropShadowEffect, QComboBox, QToolButton,
)
from qgis.core import QgsProject, QgsVectorLayer, QgsMessageLog, Qgis

from ...domain.models.enums import SyncStatusEnum, ZonalStatusEnum
from ...domain.services.mapeamento_service import format_metodo_label
from ...infra.config.settings import PLUGIN_NAME
from ..theme import SectionHeader
from ..icon_utils import tinted_icon

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)
from .upload_progress_widget import UploadProgressWidget


# Cores por sync status
_SYNC_COLORS = {
    "DOWNLOADED": "#2196F3",   # azul
    "MODIFIED": "#FF9800",     # laranja
    "UPLOADED": "#4CAF50",     # verde
    "NEW": "#9C27B0",          # roxo
    "DELETED": "#F44336",      # vermelho
}


class CamadasTab(QWidget):
    """Lista GPKGs locais com status de sync e ações — layout em cards."""

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller
        self._gpkg_list = []
        self._active_batch_uuid = None
        self._cards_by_zonal = {}        # (zonal_id, origin) -> card widget
        self._intermediate_statuses = {
            "PROCESSING", "OVERLAID", "CREATED", "CONSOLIDATING",
        }

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        section_header = SectionHeader("Camadas locais", "GeoPackage")
        self._refresh_btn = QPushButton(QIcon(os.path.join(_ICONS_DIR, "action_refresh.svg")), "Atualizar")
        self._refresh_btn.setIconSize(QSize(14, 14))
        self._refresh_btn.setFixedWidth(90)
        self._refresh_btn.setToolTip("Atualizar lista de camadas locais")
        self._refresh_btn.clicked.connect(self._refresh_list)
        section_header.add_widget(self._refresh_btn)
        layout.addWidget(section_header)

        # Barra de ordenação
        sort_row = QHBoxLayout()
        sort_row.setSpacing(4)

        sort_label = QLabel("Ordenar:")
        sort_label.setStyleSheet("font-size: 11px; color: #757575;")
        sort_row.addWidget(sort_label)

        self._sort_combo = QComboBox()
        for opt in ("#ID", "Data", "Descrição", "Tamanho", "Status"):
            self._sort_combo.addItem(opt)
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
        self._state.mapeamento_encerrado.connect(self._on_mapeamento_encerrado)
        self._state.error_occurred.connect(self._on_error)

        self._controller.zonal_upload_completed.connect(self._on_zonal_upload_done)
        self._controller.edit_tracking_done.connect(self._refresh_list)
        self._state.zonal_status_polled.connect(self._on_zonal_status_polled)

    # ================================================================
    # Card factory
    # ================================================================

    def _create_card(self, gpkg_info, counts):
        """Cria widget de card para um GPKG local."""
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

        zonal_id = gpkg_info.get("zonal_id")
        path = gpkg_info.get("path", "")
        mid = gpkg_info.get("mapeamento_id")

        # --- Linha 1: #ID + sync badge + ações ---
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        id_text = f"<b>#{mid}</b>" if mid else f"<b>Zonal {zonal_id or '?'}</b>"
        id_label = QLabel(id_text)
        id_label.setStyleSheet("font-size: 13px;")
        row1.addWidget(id_label)

        # Origin badge — distingue downloads da aba Mapeamentos vs Homologação
        from ...domain.models.enums import DownloadOrigin
        origin_enum = DownloadOrigin.coerce(gpkg_info.get("origin"))
        origin_color = "#455A64" if origin_enum == DownloadOrigin.MAPEAMENTOS else "#6A1B9A"
        origin_badge = QLabel(origin_enum.label)
        origin_badge.setStyleSheet(
            f"background-color: {origin_color}; color: white;"
            " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
        )
        origin_badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row1.addWidget(origin_badge)

        # Sync status badge
        sync_text, sync_color = self._format_sync_status(counts)
        badge = QLabel(sync_text)
        badge.setStyleSheet(
            f"background-color: {sync_color}; color: white;"
            " border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
        )
        badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row1.addWidget(badge)

        # Queue status badge (overlay/zonal) — visível somente durante polling
        queue_badge = QLabel()
        queue_badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        queue_badge.setVisible(False)
        row1.addWidget(queue_badge)
        card._queue_badge = queue_badge

        row1.addStretch()

        # Tamanho
        size_mb = gpkg_info.get("size_mb", 0)
        size_label = QLabel(f"{size_mb} MB")
        size_label.setStyleSheet("font-size: 10px; color: #757575;")
        row1.addWidget(size_label)

        layout.addLayout(row1)

        # --- Linha 2: data + método (espelha mapeamentos_tab._create_card) ---
        data_ref = "—"
        raw_date = gpkg_info.get("data_referencia")
        if raw_date:
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                data_ref = dt.strftime("%d/%m/%Y")
            except (ValueError, AttributeError):
                data_ref = str(raw_date)[:10]

        metodo_label = format_metodo_label(gpkg_info.get("metodo_apply"))
        meta = QLabel(f"{data_ref}  ·  {metodo_label}")
        meta.setStyleSheet("font-size: 11px; color: #757575;")
        layout.addWidget(meta)

        # --- Linha 3: descrição (HTML, máx 3 linhas, com tooltip) ---
        desc_label = QLabel()
        desc_label.setTextFormat(Qt.RichText)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 11px; padding: 0;")
        line_height = QFontMetrics(desc_label.font()).lineSpacing()
        desc_label.setMaximumHeight(line_height * 3 + 4)

        descricao_raw = gpkg_info.get("descricao") or ""
        plain = ""
        if descricao_raw:
            doc = QTextDocument()
            doc.setHtml(descricao_raw)
            plain = doc.toPlainText().strip()

        if plain:
            fm = QFontMetrics(desc_label.font())
            max_width = 400
            displayed = []
            for line in plain.split("\n"):
                if len(displayed) >= 3:
                    break
                displayed.append(fm.elidedText(line, Qt.ElideRight, max_width))
            desc_label.setText("<br>".join(displayed))
            desc_label.setToolTip(plain)
        else:
            fallback = f"Zonal {zonal_id or '?'}"
            desc_label.setText(f"<i style='color:#9E9E9E'>{fallback}</i>")

        layout.addWidget(desc_label)

        # --- Linha 3: ações ---
        row3 = QHBoxLayout()
        row3.setSpacing(4)
        row3.addStretch()

        modified = counts.get("MODIFIED", 0)
        new = counts.get("NEW", 0)
        deleted = counts.get("DELETED", 0)
        has_changes = modified > 0 or new > 0 or deleted > 0

        # Abrir
        btn_open = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_folder_open.svg"), "#FFFFFF"), "Abrir")
        btn_open.setIconSize(QSize(14, 14))
        btn_open.setFixedWidth(65)
        btn_open.setToolTip("Abrir GeoPackage como camada editável no QGIS")
        btn_open.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white;"
            " border: none; padding: 3px 8px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        btn_open.clicked.connect(
            lambda _, p=path, zid=zonal_id: self._open_gpkg(p, zid)
        )
        row3.addWidget(btn_open)

        # Enviar
        btn_upload = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_upload.svg"), "#FFFFFF"), "Enviar")
        btn_upload.setIconSize(QSize(14, 14))
        btn_upload.setFixedWidth(65)
        if has_changes:
            btn_upload.setEnabled(True)
            btn_upload.setStyleSheet(
                "QPushButton { background-color: #FF9800; color: white;"
                " border: none; padding: 3px 8px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #F57C00; }"
            )
            btn_upload.setToolTip(f"{modified + new + deleted} feature(s) para enviar")
            btn_upload.clicked.connect(
                lambda _, p=path: self._upload_gpkg(p)
            )
        else:
            btn_upload.setEnabled(False)
            btn_upload.setStyleSheet(
                "QPushButton { background-color: #E0E0E0; color: #9E9E9E;"
                " border: none; padding: 3px 8px; border-radius: 3px; font-size: 11px; }"
            )
            btn_upload.setToolTip("Sem alterações para enviar")
        row3.addWidget(btn_upload)

        # Remover
        btn_remove = QPushButton()
        btn_remove.setIcon(QIcon(os.path.join(_ICONS_DIR, "action_remove.svg")))
        btn_remove.setFixedWidth(28)
        btn_remove.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white;"
            " border: none; padding: 3px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #D32F2F; }"
        )
        btn_remove.setToolTip("Remover GeoPackage local")
        btn_remove.clicked.connect(
            lambda _, p=path, mod=modified + new: self._remove_gpkg(p, mod)
        )
        row3.addWidget(btn_remove)

        # Encerrar para Homologação (visível quando todo o sync está completo)
        uploaded = counts.get("UPLOADED", 0)
        total = sum(counts.values())
        all_uploaded = uploaded > 0 and uploaded == total
        btn_encerrar = None
        if mid and all_uploaded:
            btn_encerrar = QPushButton(
                tinted_icon(
                    os.path.join(_ICONS_DIR, "action_check.svg"), "#FFFFFF"
                ),
                "Encerrar",
            )
            btn_encerrar.setIconSize(QSize(14, 14))
            btn_encerrar.setFixedWidth(75)
            btn_encerrar.setToolTip("Encerrar mapeamento para homologação")
            btn_encerrar.setStyleSheet(
                "QPushButton { background-color: #FF9800; color: white;"
                " border: none; padding: 3px 8px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #F57C00; }"
                "QPushButton:disabled { background-color: #FFE0B2; color: #BDBDBD; }"
            )
            btn_encerrar.clicked.connect(
                lambda _, m=mid: self._encerrar_mapeamento(m)
            )
            row3.addWidget(btn_encerrar)

        layout.addLayout(row3)

        card.setLayout(layout)
        card._action_buttons = [btn_open, btn_upload]
        card._btn_encerrar = btn_encerrar
        card._zonal_id = zonal_id
        return card

    @staticmethod
    def _format_sync_status(counts):
        """Retorna (texto, cor) para o badge de sync status."""
        modified = counts.get("MODIFIED", 0)
        new = counts.get("NEW", 0)
        deleted = counts.get("DELETED", 0)
        uploaded = counts.get("UPLOADED", 0)
        downloaded = counts.get("DOWNLOADED", 0)
        total = counts.get("total", 0)

        # Monta partes do resumo de alteracoes pendentes
        parts = []
        if modified > 0:
            parts.append(f"{modified} editada(s)")
        if new > 0:
            parts.append(f"{new} nova(s)")
        if deleted > 0:
            parts.append(f"{deleted} removida(s)")

        if parts:
            return ", ".join(parts), _SYNC_COLORS["MODIFIED"]
        if uploaded > 0 and uploaded == total:
            return "Tudo enviado", _SYNC_COLORS["UPLOADED"]
        if downloaded > 0:
            return "Sincronizado", _SYNC_COLORS["DOWNLOADED"]
        return f"{total} feat.", "#757575"

    # ================================================================
    # Event handlers
    # ================================================================

    def _on_auth_changed(self, is_authenticated):
        if is_authenticated:
            self._refresh_list()

    def _on_loading_changed(self, operation, is_loading):
        if operation == "upload":
            for row in range(self._card_list.count()):
                widget = self._card_list.itemWidget(self._card_list.item(row))
                if widget and hasattr(widget, "_action_buttons"):
                    for btn in widget._action_buttons:
                        btn.setEnabled(not is_loading)

    def _on_upload_progress(self, status_data):
        """Atualiza widget de progresso de upload."""
        self._upload_progress.update_from_status(status_data)
        self._upload_progress.setVisible(True)
        self._active_batch_uuid = status_data.get("batchUuid", self._active_batch_uuid)

        phase = status_data.get("phase", "upload")

        # Desabilitar/habilitar botão Encerrar conforme fase de reprocessamento
        if phase == "reprocessing":
            self._set_encerrar_buttons_enabled(False, "Aguardando reprocessamento...")
        elif phase == "reprocessing_done":
            self._refresh_list()

        from ...domain.models.enums import UploadBatchStatusEnum
        status = status_data.get("status", "")
        try:
            if UploadBatchStatusEnum(status).is_terminal:
                from qgis.PyQt.QtCore import QTimer
                QTimer.singleShot(3000, self._upload_progress.finish)
        except ValueError:
            pass

    def _set_encerrar_buttons_enabled(self, enabled, tooltip=None):
        """Habilita/desabilita botões Encerrar em todos os cards."""
        for row in range(self._card_list.count()):
            widget = self._card_list.itemWidget(self._card_list.item(row))
            if widget and hasattr(widget, "_btn_encerrar") and widget._btn_encerrar:
                widget._btn_encerrar.setEnabled(enabled)
                if tooltip:
                    widget._btn_encerrar.setToolTip(tooltip)

    def _on_zonal_upload_done(self, gpkg_path, zonal_id):
        # Atualiza contagens de sync local. Sempre consulta o servidor para
        # refletir a transição real em tempo real, sem depender de cache.
        self._refresh_list()
        if zonal_id:
            self._apply_queue_badge_all(zonal_id, "PROCESSING")
            self._controller.start_polling_zonal(zonal_id)

    def _on_zonal_status_polled(self, zonal_id, status):
        """Aplica badge nos cards do zonal conforme resposta do servidor.

        Sem cache: cada resposta reflete o estado atual retornado pela API.
        Enquanto intermediário, mantém o polling; ao atingir terminal,
        apenas encerra o polling — o badge permanece visível nos cards
        já renderizados. Não dispara ``_refresh_list`` aqui para evitar
        loop (render zera badge → novo poll → terminal → refresh…).
        """
        if not status:
            return

        self._apply_queue_badge_all(zonal_id, status)

        if status in self._intermediate_statuses:
            if not self._controller.is_polling(zonal_id):
                self._controller.start_polling_zonal(zonal_id)
        else:
            self._controller.stop_polling_zonal(zonal_id)

    def _apply_queue_badge_all(self, zonal_id, status):
        """Aplica badge em todos os cards que referenciam o zonal (Mapeamentos/Homologação)."""
        for (zid, _origin), card in self._cards_by_zonal.items():
            if zid == zonal_id and hasattr(card, "_queue_badge"):
                self._apply_queue_badge(card, status)

    @staticmethod
    def _apply_queue_badge(card, status):
        """Atualiza texto/cor do badge de status da fila no card."""
        badge = getattr(card, "_queue_badge", None)
        if badge is None:
            return
        try:
            enum = ZonalStatusEnum(status)
            label_text = enum.label
            color = enum.color
        except ValueError:
            label_text = status or "Processando"
            color = "#FF9800"
        badge.setText(f"⚙ {label_text}")
        badge.setToolTip("Andamento da fila de overlay/zonal no servidor")
        badge.setStyleSheet(
            f"background-color: {color}; color: white;"
            " border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
        )
        badge.setVisible(True)

    def _on_upload_cancelled(self):
        QgsMessageLog.logMessage(
            f"Upload cancelado pelo usuario: batch {self._active_batch_uuid}",
            PLUGIN_NAME, Qgis.Info,
        )

    def _encerrar_mapeamento(self, mapeamento_id):
        """Confirma e encerra mapeamento para homologação."""
        reply = QMessageBox.question(
            self,
            "Confirmar encerramento",
            f"Encerrar mapeamento #{mapeamento_id} para homologação?\n\n"
            "Todos os zonais consolidados serão enviados para revisão.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._controller.encerrar_mapeamento(mapeamento_id)

    def _on_mapeamento_encerrado(self, data):
        """Feedback visual após encerramento bem-sucedido."""
        mid = data.get("mapeamentoId")
        msg = data.get("message", "Mapeamento encerrado")
        QMessageBox.information(
            self, "Mapeamento encerrado",
            f"Mapeamento #{mid} encerrado com sucesso.\n\n{msg}",
        )
        self._refresh_list()

    def _on_error(self, operation, message):
        """Mostra erro de encerramento ao usuario."""
        if operation == "encerrar":
            QMessageBox.warning(
                self, "Erro ao encerrar",
                f"Não foi possível encerrar o mapeamento:\n\n{message}",
            )

    # ================================================================
    # Sorting
    # ================================================================

    @staticmethod
    def _sync_priority(counts):
        """Prioridade para ordenação por status: MODIFIED > NEW > DELETED > DOWNLOADED > UPLOADED."""
        if counts.get("MODIFIED", 0) > 0:
            return 0
        if counts.get("NEW", 0) > 0:
            return 1
        if counts.get("DELETED", 0) > 0:
            return 2
        if counts.get("DOWNLOADED", 0) > 0:
            return 3
        return 4

    _SORT_KEYS = {
        "#ID": lambda e: e.get("mapeamento_id") or 0,
        "Data": lambda e: e.get("data_referencia") or "",
        "Descrição": lambda e: (e.get("descricao") or "").lower(),
        "Tamanho": lambda e: e.get("size_mb", 0),
        "Status": lambda e: CamadasTab._sync_priority(e.get("sync_counts", {})),
    }

    def _sort_gpkg_list(self):
        """Ordena _gpkg_list pelo critério selecionado."""
        key_name = self._sort_combo.currentText()
        key_fn = self._SORT_KEYS.get(key_name, self._SORT_KEYS["#ID"])
        reverse = self._sort_toggle.isChecked()
        self._gpkg_list.sort(key=key_fn, reverse=reverse)

    def _on_sort_changed(self, _index):
        """Re-renderiza lista com nova ordenação (sem re-escanear disco)."""
        self._sort_gpkg_list()
        self._render_cards()

    def _on_sort_toggled(self, checked):
        """Alterna ícone de ordenação e re-renderiza."""
        self._sort_toggle.setIcon(self._icon_sort_desc if checked else self._icon_sort_asc)
        self._sort_gpkg_list()
        self._render_cards()

    # ================================================================
    # Data & rendering
    # ================================================================

    def _refresh_list(self):
        """Atualiza lista de GPKGs locais com status de sync."""
        from ...domain.services.gpkg_service import (
            list_local_gpkgs, count_features_by_sync_status,
        )

        try:
            base_dir = self._controller.get_gpkg_base_dir()
            raw_list = list_local_gpkgs(base_dir)
            for entry in raw_list:
                entry["sync_counts"] = count_features_by_sync_status(entry["path"])
            self._gpkg_list = raw_list
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Erro ao listar GPKGs: {e}", PLUGIN_NAME, Qgis.Warning,
            )
            self._gpkg_list = []

        self._sort_gpkg_list()
        self._render_cards()
        self._fetch_statuses_for_visible_cards()

    def _fetch_statuses_for_visible_cards(self):
        """Inicia polling de status para cada zonal renderizado.

        Em vez de consulta pontual, inscreve cada zonal no polling contínuo
        do controller — assim o card reflete transições em tempo real
        (PROCESSING → OVERLAID → CONSOLIDATED). Quando atinge status
        terminal, ``_on_zonal_status_polled`` encerra o polling.
        """
        if not self._state.is_authenticated:
            return
        seen = set()
        for entry in self._gpkg_list:
            zid = entry.get("zonal_id")
            if zid is None or zid in seen:
                continue
            seen.add(zid)
            self._controller.start_polling_zonal(zid)

    def _render_cards(self):
        self._card_list.clear()
        self._cards_by_zonal = {}

        if not self._gpkg_list:
            self._status_label.setText("Nenhuma camada local encontrada")
            self._status_label.setVisible(True)
            return

        self._status_label.setVisible(False)

        for gpkg_info in self._gpkg_list:
            counts = gpkg_info.get("sync_counts", {})
            card = self._create_card(gpkg_info, counts)

            zid = gpkg_info.get("zonal_id")
            origin_key = gpkg_info.get("origin") or "mapeamentos"
            if zid is not None:
                self._cards_by_zonal[(zid, origin_key)] = card

            list_item = QListWidgetItem(self._card_list)
            list_item.setSizeHint(card.sizeHint() + QSize(0, 8))
            self._card_list.addItem(list_item)
            self._card_list.setItemWidget(list_item, card)

    # ================================================================
    # Actions
    # ================================================================

    def _open_gpkg(self, gpkg_path, zonal_id):
        """Carrega GPKG como camada editável no QGIS com edit tracking."""
        layer_name = f"Zonal {zonal_id}" if zonal_id else os.path.basename(gpkg_path)

        for existing in QgsProject.instance().mapLayers().values():
            if existing.source().split("|")[0] == gpkg_path:
                QgsMessageLog.logMessage(
                    f"Camada ja carregada: {gpkg_path}", PLUGIN_NAME, Qgis.Info,
                )
                return

        layer = QgsVectorLayer(gpkg_path, layer_name, "ogr")
        if layer.isValid():
            # Estilo: somente borda laranja, sem preenchimento
            from qgis.core import QgsFillSymbol
            from qgis.PyQt.QtCore import Qt as _Qt
            from qgis.PyQt.QtGui import QColor as _QColor
            symbol = QgsFillSymbol.createSimple({})
            sl = symbol.symbolLayer(0)
            sl.setBrushStyle(_Qt.NoBrush)
            sl.setStrokeColor(_QColor("#FF6600"))
            sl.setStrokeWidth(0.8)
            layer.renderer().setSymbol(symbol)

            QgsProject.instance().addMapLayer(layer)

            if zonal_id is not None:
                self._controller.connect_edit_tracking(
                    layer, zonal_id=zonal_id,
                )
                # Busca dados de overlay para enriquecer dialog de atributos
                self._controller.fetch_overlay_data(zonal_id)

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
        """Remove GPKG local com confirmação se há edições pendentes."""
        if modified_count > 0:
            reply = QMessageBox.question(
                self,
                "Confirmar remoção",
                f"Este GPKG tem {modified_count} feature(s) editada(s) não enviada(s).\n"
                "Deseja remover mesmo assim?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            for layer_id, layer in QgsProject.instance().mapLayers().items():
                if layer.source().split("|")[0] == gpkg_path:
                    QgsProject.instance().removeMapLayer(layer_id)

            os.remove(gpkg_path)

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

    # ================================================================
    # Public API
    # ================================================================

    def refresh(self):
        """API pública para atualizar lista de camadas."""
        self._refresh_list()

    def add_gpkg_entry(self, gpkg_info):
        """Adiciona uma entrada de GPKG após download."""
        self._refresh_list()

    def cleanup(self):
        """Cleanup de recursos da aba de camadas."""
        pass
