"""Utilidades para renderização de ícones SVG com cores dinâmicas."""

from qgis.PyQt.QtCore import Qt, QRectF
from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor
from qgis.PyQt.QtSvg import QSvgRenderer


def tinted_icon(svg_path: str, color: str, size: int = 24) -> QIcon:
    """Renderiza SVG com a cor especificada.

    Útil para ícones Lucide (stroke=currentColor) em botões
    com fundo colorido e texto branco.

    Args:
        svg_path: caminho absoluto do arquivo SVG.
        color: cor CSS (ex: "#FFFFFF", "white").
        size: tamanho base do pixmap (px).

    Returns:
        QIcon com o ícone colorido.
    """
    renderer = QSvgRenderer(svg_path)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()

    return QIcon(pixmap)
