"""Map tool para inspecao pontual de indices espectrais.

Captura clique no canvas, reprojeta o ponto para EPSG:4674 (CRS aceito
pelo backend SatIrriga) e emite o sinal point_clicked(lat, lon).
Mantem um unico QgsVertexMarker que segue o ultimo ponto consultado.
"""

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
)
from qgis.PyQt.QtCore import pyqtSignal
from qgis.gui import QgsMapToolEmitPoint, QgsVertexMarker


_CRS_4674 = QgsCoordinateReferenceSystem("EPSG:4674")
_MARKER_COLOR = "#1976D2"


class PixelInspectMapTool(QgsMapToolEmitPoint):
    """Ferramenta de mapa para consulta de pixel/indice por ponto."""

    point_clicked = pyqtSignal(float, float)  # lat, lon (EPSG:4674)

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._marker = None

    def canvasReleaseEvent(self, event):
        map_point = self.toMapCoordinates(event.pos())

        transform = QgsCoordinateTransform(
            QgsProject.instance().crs(),
            _CRS_4674,
            QgsProject.instance(),
        )
        point_4674 = transform.transform(map_point)

        self._update_marker(map_point)

        self.point_clicked.emit(
            round(point_4674.y(), 6),  # lat
            round(point_4674.x(), 6),  # lon
        )

    def _update_marker(self, map_point):
        if self._marker is None:
            self._marker = QgsVertexMarker(self._canvas)
            self._marker.setColor(QColor(_MARKER_COLOR))
            self._marker.setFillColor(QColor(_MARKER_COLOR))
            self._marker.setIconType(QgsVertexMarker.ICON_CROSS)
            self._marker.setIconSize(14)
            self._marker.setPenWidth(3)
        self._marker.setCenter(map_point)

    def clear_marker(self):
        if self._marker is not None:
            self._canvas.scene().removeItem(self._marker)
            self._marker = None

    def cleanup(self):
        self.clear_marker()
