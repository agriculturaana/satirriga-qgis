"""Widget de histórico de uploads — cards com status, métricas e comparação visual."""

import os
import tempfile
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QComboBox,
    QGraphicsDropShadowEffect,
)

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsMessageLog, Qgis,
    QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsFillSymbol, QgsRectangle,
)
from qgis.utils import iface as qgis_iface

from ...domain.models.enums import UploadBatchStatusEnum
from ...infra.config.settings import PLUGIN_NAME
from ..theme import SectionHeader

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)

_PAGE_SIZE = 10

_BATCH_COLORS = {
    "RECEIVED": "#9E9E9E",
    "STAGING": "#2196F3",
    "VALIDATING_STRUCTURE": "#2196F3",
    "VALIDATING_SCHEMA": "#2196F3",
    "VALIDATING_TOPOLOGY": "#2196F3",
    "DIFFING": "#FF9800",
    "CONFLICT_CHECKING": "#FF9800",
    "RECONCILING": "#FF9800",
    "PROMOTING": "#FF9800",
    "COMPLETED": "#4CAF50",
    "FAILED": "#F44336",
    "CANCELLED": "#616161",
}

# Cores para estilização diferencial no mapa
_DIFF_STYLES = {
    "CREATED": ("#4CAF50", 0.5),   # verde, 50% opacidade
    "MODIFIED": ("#FF9800", 0.5),   # laranja
    "DELETED": ("#F44336", 0.4),    # vermelho
    "ACCEPTED": ("#9E9E9E", 0.2),   # cinza, quase transparente
}


class UploadHistoryWidget(QWidget):
    """Histórico de uploads com cards, filtro, paginação e comparação visual."""

    def __init__(self, state, mapeamento_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._controller = mapeamento_controller
        self._current_page = 1
        self._total_pages = 1
        self._total_items = 0

        # Estado da comparação em andamento
        self._compare_pending = {}  # batch_uuid -> zonal_id
        self._compare_received = {}  # batch_uuid -> fgb_path
        self._temp_files = []       # paths de arquivos temporários para cleanup
        self._compare_layer_ids = []  # IDs de camadas de comparação no QgsProject

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        section_header = SectionHeader("Histórico de envios")

        self._filter_status = QComboBox()
        self._filter_status.addItem("Todos", "")
        self._filter_status.addItem("Concluído", "COMPLETED")
        self._filter_status.addItem("Falhou", "FAILED")
        self._filter_status.addItem("Cancelado", "CANCELLED")
        self._filter_status.addItem("Em andamento",
            "RECEIVED,STAGING,VALIDATING_STRUCTURE,VALIDATING_SCHEMA,"
            "VALIDATING_TOPOLOGY,DIFFING,CONFLICT_CHECKING,RECONCILING,PROMOTING")
        self._filter_status.currentIndexChanged.connect(self._on_filter_changed)
        section_header.add_widget(self._filter_status)

        self._refresh_btn = QPushButton(QIcon(os.path.join(_ICONS_DIR, "action_refresh.svg")), "Atualizar")
        self._refresh_btn.setIconSize(QSize(14, 14))
        self._refresh_btn.setFixedWidth(90)
        self._refresh_btn.clicked.connect(self._request_page)
        section_header.add_widget(self._refresh_btn)

        layout.addWidget(section_header)

        # Lista de cards
        self._card_list = QListWidget()
        self._card_list.setSelectionMode(QListWidget.NoSelection)
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

    def _connect_signals(self):
        self._state.upload_history_changed.connect(self._on_data_loaded)
        self._state.loading_changed.connect(self._on_loading_changed)
        self._state.error_occurred.connect(self._on_error)
        self._controller.versions_loaded.connect(self._on_versions_loaded)
        self._controller.compare_fgb_ready.connect(self._on_compare_fgb_ready)

    # ================================================================
    # Card factory
    # ================================================================

    def _create_card(self, item):
        """Cria card para um UploadHistoryItem."""
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            "QFrame { border: 1px solid palette(mid); border-radius: 6px;"
            " padding: 6px; background: palette(base); }"
        )

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 40))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # --- Linha 1: ID + status + data ---
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        id_label = QLabel(f"<b>#{item.mapeamento_id}</b>")
        id_label.setStyleSheet("font-size: 13px;")
        row1.addWidget(id_label)

        status_text = item.status
        status_color = _BATCH_COLORS.get(item.status, "#9E9E9E")
        try:
            status_enum = UploadBatchStatusEnum(item.status)
            status_text = status_enum.label
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

        created = "—"
        if item.created_at:
            try:
                dt = datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
                created = dt.strftime("%d/%m/%Y %H:%M")
            except (ValueError, AttributeError):
                created = str(item.created_at)[:16]

        date_label = QLabel(created)
        date_label.setStyleSheet("font-size: 10px; color: #757575;")
        row1.addWidget(date_label)

        layout.addLayout(row1)

        # --- Linha 2: descrição + autor ---
        desc = item.mapeamento_descricao or "—"
        if len(desc) > 80:
            desc = desc[:77] + "..."
        meta = QLabel(f"{desc}  ·  Autor: {item.author or '—'}")
        meta.setStyleSheet("font-size: 11px; color: #757575;")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        # --- Linha 3: métricas ---
        parts = []
        if item.feature_count:
            parts.append(f"{item.feature_count} feições")
        if item.modified_count:
            parts.append(f"{item.modified_count} editadas")
        if item.new_count:
            parts.append(f"{item.new_count} novas")
        if item.deleted_count:
            parts.append(f"{item.deleted_count} removidas")
        if item.conflict_count:
            parts.append(f"{item.conflict_count} conflitos")
        if item.invalid_count:
            parts.append(f"{item.invalid_count} inválidas")

        if parts:
            metrics = QLabel("  ·  ".join(parts))
            metrics.setStyleSheet("font-size: 11px;")
            layout.addWidget(metrics)

        # --- Linha 4: erro ---
        if item.error_log and item.status == "FAILED":
            error_text = str(item.error_log)
            if len(error_text) > 120:
                error_text = error_text[:117] + "..."
            err_label = QLabel(error_text)
            err_label.setStyleSheet("font-size: 10px; color: #F44336;")
            err_label.setWordWrap(True)
            err_label.setToolTip(str(item.error_log))
            layout.addWidget(err_label)

        # --- Linha 5: duração ---
        if item.completed_at and item.created_at:
            try:
                t0 = datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(item.completed_at.replace("Z", "+00:00"))
                secs = int((t1 - t0).total_seconds())
                duration = f"{secs}s" if secs < 60 else f"{secs // 60}m {secs % 60}s"
                dur_label = QLabel(f"Duração: {duration}")
                dur_label.setStyleSheet("font-size: 10px; color: #757575;")
                layout.addWidget(dur_label)
            except (ValueError, AttributeError):
                pass

        # --- Linha 6: ações ---
        if item.status == "COMPLETED":
            row_actions = QHBoxLayout()
            row_actions.addStretch()

            btn_compare = QPushButton("Comparar versões")
            btn_compare.setToolTip("Comparar esta versão com outra no mapa")
            btn_compare.setStyleSheet(
                "QPushButton { background-color: #1976D2; color: white;"
                " border: none; padding: 3px 12px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #1565C0; }"
            )
            btn_compare.clicked.connect(
                lambda _, zid=item.zonal_id: self._on_compare_clicked(zid)
            )
            row_actions.addWidget(btn_compare)

            layout.addLayout(row_actions)

        card.setLayout(layout)
        return card

    # ================================================================
    # Comparação
    # ================================================================

    def _on_compare_clicked(self, zonal_id):
        """Inicia fluxo de comparação: busca versões disponíveis."""
        self._controller.load_versions(zonal_id)

    def _on_versions_loaded(self, zonal_id, versions_data):
        """Versões carregadas — abre diálogo de seleção."""
        versions = versions_data.get("versions", [])
        if len(versions) < 2:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Comparação",
                "É necessário ao menos 2 versões para comparar."
            )
            return

        from ..dialogs.compare_dialog import CompareDialog
        dialog = CompareDialog(versions_data, parent=self)
        if dialog.exec_() == CompareDialog.Accepted:
            result = dialog.get_result()
            if result:
                batch_a, batch_b = result
                self._start_compare_download(zonal_id, batch_a, batch_b)

    def _start_compare_download(self, zonal_id, batch_a, batch_b):
        """Dispara download dos FlatGeobuf de ambas as versões."""
        self._compare_pending = {batch_a: zonal_id, batch_b: zonal_id}
        self._compare_received = {}
        self._controller.download_compare_fgb(zonal_id, batch_a)
        self._controller.download_compare_fgb(zonal_id, batch_b)

    def _on_compare_fgb_ready(self, zonal_id, batch_uuid, layer_bytes):
        """Recebe GeoPackage de uma versão. Quando ambas chegam, carrega no mapa."""
        if batch_uuid not in self._compare_pending:
            return

        # Salvar GPKG em arquivo temporário
        tmp = tempfile.NamedTemporaryFile(
            suffix=f"_{batch_uuid[:8]}.gpkg", delete=False, prefix="compare_"
        )
        tmp.write(layer_bytes)
        tmp.close()

        self._compare_received[batch_uuid] = tmp.name
        self._temp_files.append(tmp.name)
        self._compare_pending.pop(batch_uuid, None)

        QgsMessageLog.logMessage(
            f"[Compare] GPKG recebido: {batch_uuid[:8]} ({len(layer_bytes)} bytes)",
            PLUGIN_NAME, Qgis.Info,
        )

        # Quando ambos chegaram, carregar no mapa
        if not self._compare_pending and len(self._compare_received) == 2:
            self._load_compare_layers(zonal_id)

    def _load_compare_layers(self, zonal_id):
        """Carrega dois GeoPackages como camadas com estilo diferencial."""
        uuids = list(self._compare_received.keys())
        paths = [self._compare_received[u] for u in uuids]

        for i, (uuid, path) in enumerate(zip(uuids, paths)):
            label = "A (base)" if i == 0 else "B (comparar)"
            layer_name = f"Comparação {label} — Zonal {zonal_id} [{uuid[:8]}]"

            layer = QgsVectorLayer(path, layer_name, "ogr")
            if not layer.isValid():
                QgsMessageLog.logMessage(
                    f"[Compare] Camada inválida: {path}",
                    PLUGIN_NAME, Qgis.Warning,
                )
                continue

            self._apply_diff_style(layer)
            QgsProject.instance().addMapLayer(layer)
            self._compare_layer_ids.append(layer.id())

            QgsMessageLog.logMessage(
                f"[Compare] Camada carregada: {layer_name} ({layer.featureCount()} feições)",
                PLUGIN_NAME, Qgis.Info,
            )

        self._compare_received.clear()

        # Zoom para a extensão combinada das camadas de comparação
        self._zoom_to_compare_layers()

    def _zoom_to_compare_layers(self):
        """Ajusta o mapa para exibir a extensão combinada das camadas de comparação."""
        combined = QgsRectangle()
        for layer_id in self._compare_layer_ids:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer and layer.featureCount() > 0:
                combined.combineExtentWith(layer.extent())

        if not combined.isNull() and qgis_iface:
            combined.scale(1.1)  # margem de 10%
            canvas = qgis_iface.mapCanvas()
            canvas.setExtent(combined)
            canvas.refresh()

    @staticmethod
    def _apply_diff_style(layer):
        """Categoriza por editAction com uma cor por valor.

        Trocado de QgsRuleBasedRenderer (que tinha root rule com simbolo
        padrao azul renderizando todas as features por baixo das
        categorias semitransparentes, mascarando-as) para
        QgsCategorizedSymbolRenderer, idiomatico para "uma cor por valor
        de coluna" e sem fallback indesejado.
        """
        categories = []
        for action, (color, opacity) in _DIFF_STYLES.items():
            symbol = QgsFillSymbol.createSimple({
                "color": color,
                "outline_color": color,
                "outline_width": "0.5",
            })
            symbol.setOpacity(opacity)
            categories.append(QgsRendererCategory(action, symbol, action))

        renderer = QgsCategorizedSymbolRenderer("editAction", categories)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    # ================================================================
    # Data loading
    # ================================================================

    def load(self):
        self._current_page = 1
        self._request_page()

    def _request_page(self):
        status = self._filter_status.currentData() or ""
        self._controller.load_upload_history(
            page=self._current_page,
            size=_PAGE_SIZE,
            status=status,
        )

    def _on_data_loaded(self, items, pagination):
        self._card_list.clear()
        self._current_page = pagination.get("page", 1)
        self._total_pages = pagination.get("totalPages", 1)
        self._total_items = pagination.get("total", len(items))

        if not items:
            self._status_label.setText("Nenhum envio encontrado")
            self._status_label.setStyleSheet("font-size: 11px; color: #757575;")
            self._status_label.setVisible(True)
        else:
            self._status_label.setVisible(False)

        for item in items:
            card = self._create_card(item)
            list_item = QListWidgetItem(self._card_list)
            list_item.setSizeHint(card.sizeHint() + QSize(0, 8))
            self._card_list.addItem(list_item)
            self._card_list.setItemWidget(list_item, card)

        self._update_pagination()

    # ================================================================
    # Filters / pagination
    # ================================================================

    def _on_filter_changed(self, _index):
        self._current_page = 1
        self._request_page()

    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._request_page()

    def _on_next_page(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._request_page()

    def _update_pagination(self):
        total = self._total_items
        suffix = "registro" if total == 1 else "registros"
        self._page_label.setText(
            f"{self._current_page} / {self._total_pages}  ({total} {suffix})"
        )
        self._btn_prev.setEnabled(self._current_page > 1)
        self._btn_next.setEnabled(self._current_page < self._total_pages)

    def _on_loading_changed(self, operation, is_loading):
        if operation == "upload_history":
            self._refresh_btn.setEnabled(not is_loading)
            if is_loading:
                self._status_label.setText("Carregando histórico...")
                self._status_label.setStyleSheet("font-size: 11px;")
                self._status_label.setVisible(True)
            else:
                self._status_label.setVisible(False)

    def _on_error(self, operation, message):
        if operation == "upload_history":
            self._status_label.setText(f"Erro: {message}")
            self._status_label.setStyleSheet("color: #F44336; font-size: 11px;")
            self._status_label.setVisible(True)
        elif operation == "compare":
            # Resetar estado de comparação incompleta
            self._compare_pending.clear()
            self._compare_received.clear()

    def cleanup(self):
        """Desconecta signals, remove camadas de comparação e arquivos temporários."""
        # Desconectar signals para evitar callbacks em objeto destruído
        try:
            self._state.upload_history_changed.disconnect(self._on_data_loaded)
            self._state.loading_changed.disconnect(self._on_loading_changed)
            self._state.error_occurred.disconnect(self._on_error)
            self._controller.versions_loaded.disconnect(self._on_versions_loaded)
            self._controller.compare_fgb_ready.disconnect(self._on_compare_fgb_ready)
        except (RuntimeError, TypeError):
            pass

        # Remover camadas de comparação do projeto
        for layer_id in self._compare_layer_ids:
            try:
                QgsProject.instance().removeMapLayer(layer_id)
            except RuntimeError:
                pass
        self._compare_layer_ids.clear()

        # Remover arquivos temporários
        for path in self._temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._temp_files.clear()
