"""Map tool para marcacao de pontos de serie temporal."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsWkbTypes,
)
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand, QgsVertexMarker

from ...domain.models.timeseries import TimeSeriesPoint


# Paleta de cores ciclica (mesma do web client)
_COLORS = [
    "#4C63B6", "#E8572A", "#2E8B57", "#9B59B6",
    "#E67E22", "#1ABC9C", "#E74C3C", "#3498DB",
]

_CRS_4674 = QgsCoordinateReferenceSystem("EPSG:4674")


class _PointLabel:
    """Label de texto sobre o canvas para identificar um ponto."""

    def __init__(self, canvas, map_point, point_id, color):
        from qgis.PyQt.QtWidgets import QLabel
        self._canvas = canvas
        self._map_point = map_point

        self._widget = QLabel(str(point_id), canvas)
        self._widget.setAlignment(Qt.AlignCenter)
        self._widget.setFixedSize(20, 20)
        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        self._widget.setFont(font)
        self._widget.setStyleSheet(
            f"background-color: {color}; color: white; "
            f"border-radius: 10px; border: 1px solid white;"
        )
        self._update_position()
        self._widget.show()

        canvas.extentsChanged.connect(self._update_position)

    def _update_position(self):
        pixel = self._canvas.getCoordinateTransform().transform(self._map_point)
        self._widget.move(int(pixel.x()) - 10, int(pixel.y()) - 28)

    def remove(self):
        try:
            self._canvas.extentsChanged.disconnect(self._update_position)
        except (TypeError, RuntimeError):
            pass
        self._widget.deleteLater()


class TimeSeriesMapTool(QgsMapToolEmitPoint):
    """Ferramenta de mapa para marcar pontos de consulta de serie temporal."""

    point_added = pyqtSignal(object)    # TimeSeriesPoint
    points_cleared = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._points = []        # List[TimeSeriesPoint]
        self._markers = []       # List[QgsVertexMarker]
        self._labels = []        # List[_PointLabel]
        self._next_id = 1

    def canvasReleaseEvent(self, event):
        """Captura clique no mapa e cria ponto de serie temporal."""
        map_point = self.toMapCoordinates(event.pos())

        # Transforma para EPSG:4674
        transform = QgsCoordinateTransform(
            QgsProject.instance().crs(), _CRS_4674, QgsProject.instance(),
        )
        point_4674 = transform.transform(map_point)

        color = _COLORS[(self._next_id - 1) % len(_COLORS)]

        ts_point = TimeSeriesPoint(
            id=self._next_id,
            color=color,
            lon=round(point_4674.x(), 6),
            lat=round(point_4674.y(), 6),
        )

        # Marcador visual (ponto colorido no mapa)
        marker = QgsVertexMarker(self._canvas)
        marker.setCenter(map_point)
        marker.setColor(QColor(color))
        marker.setFillColor(QColor(color))
        marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
        marker.setIconSize(12)
        marker.setPenWidth(2)

        # Label com número do ponto
        label = _PointLabel(self._canvas, map_point, self._next_id, color)

        self._points.append(ts_point)
        self._markers.append(marker)
        self._labels.append(label)
        self._next_id += 1

        self.point_added.emit(ts_point)

    def get_points(self):
        """Retorna lista de pontos marcados."""
        return list(self._points)

    def point_count(self):
        """Retorna quantidade de pontos marcados."""
        return len(self._points)

    def clear_points(self):
        """Remove todos os pontos, marcadores e labels."""
        for marker in self._markers:
            self._canvas.scene().removeItem(marker)
        for label in self._labels:
            label.remove()
        self._markers.clear()
        self._labels.clear()
        self._points.clear()
        self._next_id = 1
        self.points_cleared.emit()

    def cleanup(self):
        """Limpeza completa ao descarregar o plugin."""
        self.clear_points()
