"""Controller de edicao de atributos — escuta selecao no mapa.

Quando o layer ativo e SatIrriga (tem campo _sync_status) e exatamente
1 feature e selecionada, abre o AttributeEditDialog.
"""

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsVectorLayer, QgsMessageLog, Qgis

from ...infra.config.settings import PLUGIN_NAME


class AttributeEditController(QObject):
    """Escuta selecao no canvas e abre dialog de edicao de atributos."""

    feature_saved = pyqtSignal(int)  # fid — propaga do dialog para o plugin

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._current_layer = None
        self._dialog = None
        self._overlay_data = None  # dict {zg_id: overlay} from /api/zonal/:id/overlay-data

        # Conecta troca de layer ativo
        self._canvas.currentLayerChanged.connect(self._on_layer_changed)

        # Verifica layer atual ao inicializar
        current = self._canvas.currentLayer()
        if current and self._is_satirriga_layer(current):
            self._connect_layer(current)

    def cleanup(self):
        """Desconecta todos os sinais — chamar no unload."""
        try:
            self._canvas.currentLayerChanged.disconnect(self._on_layer_changed)
        except TypeError:
            pass

        self._disconnect_layer()
        self._close_dialog()

    def _on_layer_changed(self, layer):
        """Handler para troca de layer ativo no canvas."""
        self._disconnect_layer()
        self._close_dialog()

        if layer and self._is_satirriga_layer(layer):
            self._connect_layer(layer)

    def _connect_layer(self, layer):
        """Conecta selectionChanged do layer SatIrriga."""
        self._current_layer = layer
        layer.selectionChanged.connect(self._on_selection_changed)

    def _disconnect_layer(self):
        """Desconecta selectionChanged do layer anterior."""
        if self._current_layer is not None:
            try:
                self._current_layer.selectionChanged.disconnect(
                    self._on_selection_changed
                )
            except (TypeError, RuntimeError):
                pass
            self._current_layer = None

    def _close_dialog(self):
        """Fecha dialog existente se houver."""
        dlg = self._dialog
        self._dialog = None
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()

    def _on_selection_changed(self, selected, deselected, clear_and_select):
        """Handler para mudanca de selecao no layer ativo."""
        layer = self._current_layer
        if layer is None:
            return

        selected_ids = layer.selectedFeatureIds()
        if len(selected_ids) != 1:
            self._close_dialog()
            return

        fid = selected_ids[0]
        feature = layer.getFeature(fid)
        if not feature.isValid():
            return

        self._close_dialog()
        self._open_dialog(layer, feature)

    def set_overlay_data(self, data):
        """Define dados de overlay para enriquecer o dialog de atributos.

        Se o dialog já estiver aberto, injeta a seção overlay dinamicamente.
        """
        self._overlay_data = data

        if self._dialog is not None and data:
            self._dialog.inject_overlay(data)

    def _open_dialog(self, layer, feature):
        """Abre dialog de edicao de atributos."""
        from ...ui.dialogs.attribute_dialog import AttributeEditDialog

        self._dialog = AttributeEditDialog(
            layer=layer,
            feature=feature,
            parent=self._canvas.window(),
            overlay_data=self._overlay_data,
        )
        self._dialog.feature_saved.connect(self._on_feature_saved)
        self._dialog.finished.connect(self._on_dialog_finished)
        self._dialog.show()

        QgsMessageLog.logMessage(
            f"Dialog de atributos aberto para feature #{feature.id()}",
            PLUGIN_NAME, Qgis.Info,
        )

    def _on_feature_saved(self, fid):
        """Handler apos salvar feature — propaga signal para o plugin."""
        QgsMessageLog.logMessage(
            f"Atributos da feature #{fid} salvos",
            PLUGIN_NAME, Qgis.Info,
        )
        self.feature_saved.emit(fid)

    def _on_dialog_finished(self, result):
        """Handler quando dialog fecha (accept ou reject)."""
        if self._dialog is not None:
            self._dialog.deleteLater()
            self._dialog = None

    @staticmethod
    def _is_satirriga_layer(layer):
        """Verifica se o layer e SatIrriga (tem campo _sync_status)."""
        return (
            isinstance(layer, QgsVectorLayer)
            and layer.isValid()
            and layer.fields().indexOf("_sync_status") >= 0
        )
