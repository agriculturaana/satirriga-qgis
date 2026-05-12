"""Controller de inspecao pontual de indices espectrais.

Liga PixelInspectMapTool -> TileIndexesService -> PixelInspectDialog.
Resolve image_ids dos grupos de data expandidos na arvore de camadas
(custom property satirriga/image_id gravada em plugin._on_raster_layers_ready).
"""

from typing import List, Optional

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import (
    Qgis,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMessageLog,
    QgsProject,
)

from ...domain.services.tile_indexes_service import TileIndexesService
from ...infra.config.settings import PLUGIN_NAME
from ...ui.tools.pixel_inspect_map_tool import PixelInspectMapTool


_MAX_IMAGE_IDS = 10  # limite defensivo de payload
_IMAGE_ID_PROP = "satirriga/image_id"


class PixelInspectController(QObject):
    """Coordena map tool, servico HTTP e dialog flutuante."""

    indexes_ready = pyqtSignal(float, float, list)   # lat, lon, List[SceneIndexes]
    indexes_error = pyqtSignal(str)                  # mensagem
    indexes_loading = pyqtSignal(float, float)       # lat, lon
    indexes_no_images = pyqtSignal(float, float)     # nenhum raster ativo

    def __init__(self, canvas, http_client, config_repo, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._http = http_client
        self._service = TileIndexesService(http_client, config_repo)

        self._tool = PixelInspectMapTool(canvas)
        self._tool.point_clicked.connect(self._on_point_clicked)

        self._http.request_finished.connect(self._on_request_finished)
        self._http.request_error.connect(self._on_request_error)

        self._pending_id: Optional[str] = None
        self._pending_coords: Optional[tuple] = None  # (lat, lon)
        self._pending_image_ids: List[str] = []

    # ------------------------------------------------------------------
    # Map tool lifecycle
    # ------------------------------------------------------------------

    @property
    def map_tool(self) -> PixelInspectMapTool:
        return self._tool

    def activate(self):
        self._canvas.setMapTool(self._tool)

    def deactivate(self):
        self._canvas.unsetMapTool(self._tool)

    def clear_marker(self):
        self._tool.clear_marker()

    def cleanup(self):
        self._cancel_pending()
        self.deactivate()
        self._tool.cleanup()
        self._service.clear_cache()

    # ------------------------------------------------------------------
    # Click handling
    # ------------------------------------------------------------------

    def _on_point_clicked(self, lat: float, lon: float):
        image_ids = self._resolve_active_image_ids()
        if not image_ids:
            self.indexes_no_images.emit(lat, lon)
            return

        # Cache hit -> entrega imediata
        cached = self._service.cached_for(image_ids, lat, lon)
        if cached is not None:
            self.indexes_ready.emit(lat, lon, cached)
            return

        # Descarta request anterior (resposta seria irrelevante)
        self._cancel_pending()

        self.indexes_loading.emit(lat, lon)
        self._pending_image_ids = image_ids
        self._pending_coords = (lat, lon)
        self._pending_id = self._service.request(image_ids, lat, lon)

        QgsMessageLog.logMessage(
            f"[PixelInspect] POST indices: lat={lat} lon={lon} "
            f"({len(image_ids)} cena(s))",
            PLUGIN_NAME, Qgis.Info,
        )

    def _on_request_finished(self, request_id, status_code, body):
        if request_id != self._pending_id:
            return
        lat, lon = self._pending_coords or (0.0, 0.0)
        image_ids = self._pending_image_ids
        self._pending_id = None
        self._pending_coords = None
        self._pending_image_ids = []

        scenes = self._service.parse_response(body)
        self._service.store(image_ids, lat, lon, scenes)
        self.indexes_ready.emit(lat, lon, scenes)

    def _on_request_error(self, request_id, error_msg):
        if request_id != self._pending_id:
            return
        self._pending_id = None
        self._pending_coords = None
        self._pending_image_ids = []
        QgsMessageLog.logMessage(
            f"[PixelInspect] Erro: {error_msg}",
            PLUGIN_NAME, Qgis.Warning,
        )
        self.indexes_error.emit(error_msg)

    def _cancel_pending(self):
        if self._pending_id:
            try:
                self._http.cancel(self._pending_id)
            except Exception:
                pass
        self._pending_id = None
        self._pending_coords = None
        self._pending_image_ids = []

    # ------------------------------------------------------------------
    # Resolucao de image_ids ativos
    # ------------------------------------------------------------------

    def _resolve_active_image_ids(self) -> List[str]:
        """Coleta image_ids dos grupos de data expandidos na arvore.

        Estrategia (em ordem de prioridade):
            1. Grupos de data com isExpanded()=True → todas as camadas SatIrriga.
            2. Fallback: primeiro grupo de data encontrado (mais recente).

        Deduplica preservando ordem; limita a _MAX_IMAGE_IDS por payload.
        """
        root = QgsProject.instance().layerTreeRoot()

        date_groups = list(self._iter_date_groups(root))
        if not date_groups:
            return []

        expanded = [g for g in date_groups if g.isExpanded()]
        target_groups = expanded or date_groups[:1]

        ids: List[str] = []
        seen = set()
        for group in target_groups:
            for img_id in self._collect_image_ids(group):
                if img_id and img_id not in seen:
                    seen.add(img_id)
                    ids.append(img_id)
                    if len(ids) >= _MAX_IMAGE_IDS:
                        return ids
        return ids

    def _iter_date_groups(self, node):
        """Itera grupos folha que contenham camadas com custom property image_id.

        Funciona independente da profundidade da hierarquia ("SatIrriga /
        Imagens" -> "Cenas" -> data). Reconhece como "grupo de data"
        qualquer QgsLayerTreeGroup cujos filhos diretos sejam grupos de
        banda contendo camadas SatIrriga.
        """
        if not isinstance(node, QgsLayerTreeGroup):
            return
        # Grupo "de data" = tem ao menos um filho que e grupo de banda
        # (subgrupo cujos filhos sao QgsLayerTreeLayer com image_id).
        if self._is_date_group(node):
            yield node
            return
        for child in node.children():
            yield from self._iter_date_groups(child)

    def _is_date_group(self, group: QgsLayerTreeGroup) -> bool:
        for child in group.children():
            if isinstance(child, QgsLayerTreeGroup):
                for sub in child.children():
                    if isinstance(sub, QgsLayerTreeLayer):
                        layer = sub.layer()
                        if layer and layer.customProperty(_IMAGE_ID_PROP):
                            return True
        return False

    def _collect_image_ids(self, group: QgsLayerTreeGroup):
        """Yield image_ids unicos das camadas SatIrriga sob `group`."""
        for child in self._iter_layer_nodes(group):
            layer = child.layer()
            if not layer:
                continue
            img_id = layer.customProperty(_IMAGE_ID_PROP)
            if img_id and "-" not in img_id:  # ignora image_ids compostos (diff)
                yield img_id

    def _iter_layer_nodes(self, node):
        if isinstance(node, QgsLayerTreeLayer):
            yield node
            return
        if isinstance(node, QgsLayerTreeGroup):
            for child in node.children():
                yield from self._iter_layer_nodes(child)
