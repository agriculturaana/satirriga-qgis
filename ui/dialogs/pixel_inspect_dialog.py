"""Dialog flutuante para exibir indices espectrais consultados por ponto.

QDialog nao-modal (Qt.Tool, sempre-on-top) que sobrevive a multiplos
cliques no canvas, atualizando o conteudo em vez de reabrir.
"""

from typing import List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...domain.models.pixel_indexes import SceneIndexes


# Ordem e definicoes dos indices renderizados — espelha layer-indexes-panel.types.ts
_INDEX_DEFS = [
    ("ndvi",   "NDVI",   "Vegetação"),
    ("savi",   "SAVI",   "Veg. ajustado ao solo"),
    ("evi",    "EVI",    "Vegetação melhorado"),
    ("ndwi",   "NDWI",   "Água"),
    ("mndwi",  "MNDWI",  "Água modificado"),
    ("albedo", "Albedo", "Reflectância média"),
]

# Faixas de severidade -> cor do dot (verde alto / amarelo medio / vermelho baixo)
_COLOR_HIGH = "#2E7D32"
_COLOR_MID = "#F9A825"
_COLOR_LOW = "#C62828"
_COLOR_NONE = "#9E9E9E"


def _severity_color(key: str, value: Optional[float]) -> str:
    """Retorna cor do dot conforme faixa do indice."""
    if value is None:
        return _COLOR_NONE
    if key in ("ndvi", "evi", "savi"):
        if value >= 0.5:
            return _COLOR_HIGH
        if value >= 0.2:
            return _COLOR_MID
        return _COLOR_LOW
    if key in ("ndwi", "mndwi"):
        if value >= 0.0:
            return _COLOR_HIGH
        if value >= -0.3:
            return _COLOR_MID
        return _COLOR_LOW
    if key == "albedo":
        if value >= 0.3:
            return _COLOR_HIGH
        if value >= 0.15:
            return _COLOR_MID
        return _COLOR_LOW
    return _COLOR_NONE


class PixelInspectDialog(QDialog):
    """Painel flutuante com 6 indices espectrais por ponto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scenes: List[SceneIndexes] = []
        self._current_index = 0
        self._index_value_labels = {}  # key -> QLabel valor
        self._index_dot_labels = {}    # key -> QLabel dot

        self.setWindowTitle("Inspeção de pixel — SatIrriga")
        self.setWindowFlags(
            Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint
        )
        self.setModal(False)
        self.setMinimumWidth(360)
        self.setMaximumWidth(440)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        # --- Header: coordenadas + status ---
        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        self._coords_label = QLabel("Clique no mapa para inspecionar.")
        self._coords_label.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #263238; "
            "border: none; background: transparent;"
        )
        header_row.addWidget(self._coords_label, 1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "font-size: 10px; color: #757575; border: none; background: transparent;"
        )
        header_row.addWidget(self._status_label)

        root.addLayout(header_row)

        # --- Dropdown de cena (visivel se >1) ---
        self._scene_combo = QComboBox()
        self._scene_combo.setVisible(False)
        self._scene_combo.currentIndexChanged.connect(self._on_scene_changed)
        root.addWidget(self._scene_combo)

        # --- Grid 2x3 dos indices ---
        self._grid_frame = QFrame()
        self._grid_frame.setFrameShape(QFrame.NoFrame)
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        for pos, (key, label, tooltip) in enumerate(_INDEX_DEFS):
            row, col = divmod(pos, 2)
            cell = self._build_cell(key, label, tooltip)
            grid.addWidget(cell, row, col)

        self._grid_frame.setLayout(grid)
        root.addWidget(self._grid_frame)

        # --- Mensagem de estado vazio/erro ---
        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignCenter)
        self._message_label.setStyleSheet(
            "font-size: 11px; color: #757575; border: none; "
            "background: transparent; padding: 6px;"
        )
        self._message_label.setVisible(False)
        root.addWidget(self._message_label)

        # --- Acoes ---
        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)

        self._btn_clear = QPushButton("Limpar marcador")
        self._btn_clear.setStyleSheet(
            "QPushButton { padding: 4px 10px; border-radius: 4px; "
            "font-size: 11px; }"
        )
        actions_row.addWidget(self._btn_clear)

        actions_row.addStretch()

        self._btn_close = QPushButton("Fechar")
        self._btn_close.setFixedWidth(72)
        self._btn_close.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "border: none; padding: 5px 12px; border-radius: 4px; "
            "font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        self._btn_close.clicked.connect(self.hide)
        actions_row.addWidget(self._btn_close)

        root.addLayout(actions_row)

        self.setLayout(root)

    def _build_cell(self, key: str, label: str, tooltip: str) -> QWidget:
        cell = QFrame()
        cell.setFrameShape(QFrame.StyledPanel)
        cell.setStyleSheet(
            "QFrame { background-color: #FAFAFA; border: 1px solid #E0E0E0; "
            "border-radius: 4px; padding: 4px 6px; }"
        )
        cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        cell.setToolTip(tooltip)

        cell_layout = QVBoxLayout()
        cell_layout.setContentsMargins(6, 4, 6, 4)
        cell_layout.setSpacing(2)

        # Linha topo: label + dot
        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        top_row.setContentsMargins(0, 0, 0, 0)

        label_widget = QLabel(label)
        label_widget.setStyleSheet(
            "font-size: 10px; font-weight: bold; color: #455A64; "
            "border: none; background: transparent;"
        )
        top_row.addWidget(label_widget)

        top_row.addStretch()

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background-color: {_COLOR_NONE}; border-radius: 4px; border: none;"
        )
        top_row.addWidget(dot)

        cell_layout.addLayout(top_row)

        # Linha valor
        value = QLabel("—")
        value.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #212121; "
            "font-family: monospace; border: none; background: transparent;"
        )
        cell_layout.addWidget(value)

        cell.setLayout(cell_layout)
        self._index_value_labels[key] = value
        self._index_dot_labels[key] = dot
        return cell

    # ------------------------------------------------------------------
    # API publica — chamada pelo controller
    # ------------------------------------------------------------------

    def show_loading(self, lat: float, lon: float):
        self._coords_label.setText(self._format_coords(lat, lon))
        self._status_label.setText("Consultando…")
        self._status_label.setStyleSheet(
            "font-size: 10px; color: #1976D2; border: none; background: transparent;"
        )
        self._message_label.setVisible(False)
        self._grid_frame.setEnabled(False)
        self._reset_values()
        self._show_and_raise()

    def show_results(self, lat: float, lon: float, scenes: List[SceneIndexes]):
        self._coords_label.setText(self._format_coords(lat, lon))
        self._scenes = list(scenes)
        self._grid_frame.setEnabled(True)

        if not self._scenes:
            self._scene_combo.setVisible(False)
            self._reset_values()
            self._status_label.setText("")
            self._message_label.setText(
                "Sem dados de índice para este ponto nas cenas selecionadas."
            )
            self._message_label.setVisible(True)
            self._show_and_raise()
            return

        # Popula dropdown se houver mais de uma cena
        self._scene_combo.blockSignals(True)
        self._scene_combo.clear()
        for scene in self._scenes:
            self._scene_combo.addItem(scene.display_label())
        self._scene_combo.setCurrentIndex(0)
        self._scene_combo.blockSignals(False)
        self._scene_combo.setVisible(len(self._scenes) > 1)

        self._current_index = 0
        self._render_scene(self._scenes[0])
        self._status_label.setText(
            f"{len(self._scenes)} cena(s)"
        )
        self._status_label.setStyleSheet(
            "font-size: 10px; color: #2E7D32; border: none; background: transparent;"
        )
        self._message_label.setVisible(False)
        self._show_and_raise()

    def show_error(self, lat: Optional[float], lon: Optional[float], message: str):
        if lat is not None and lon is not None:
            self._coords_label.setText(self._format_coords(lat, lon))
        self._status_label.setText("Erro")
        self._status_label.setStyleSheet(
            "font-size: 10px; color: #C62828; border: none; background: transparent;"
        )
        self._scene_combo.setVisible(False)
        self._reset_values()
        self._grid_frame.setEnabled(False)
        self._message_label.setText(f"Falha ao consultar: {message}")
        self._message_label.setVisible(True)
        self._show_and_raise()

    def show_no_images(self, lat: float, lon: float):
        self._coords_label.setText(self._format_coords(lat, lon))
        self._status_label.setText("Sem cena ativa")
        self._status_label.setStyleSheet(
            "font-size: 10px; color: #E65100; border: none; background: transparent;"
        )
        self._scene_combo.setVisible(False)
        self._reset_values()
        self._grid_frame.setEnabled(False)
        self._message_label.setText(
            "Expanda um grupo de data em \"SatIrriga / Imagens / Cenas\" "
            "para selecionar quais cenas consultar."
        )
        self._message_label.setVisible(True)
        self._show_and_raise()

    def bind_clear_marker(self, callback):
        """Conecta acao do botao 'Limpar marcador'."""
        try:
            self._btn_clear.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._btn_clear.clicked.connect(callback)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _on_scene_changed(self, idx):
        if 0 <= idx < len(self._scenes):
            self._current_index = idx
            self._render_scene(self._scenes[idx])

    def _render_scene(self, scene: SceneIndexes):
        for key, _label, _tip in _INDEX_DEFS:
            value = getattr(scene, key, None)
            self._index_value_labels[key].setText(self._format_value(value))
            color = _severity_color(key, value)
            self._index_dot_labels[key].setStyleSheet(
                f"background-color: {color}; border-radius: 4px; border: none;"
            )

    def _reset_values(self):
        for key, _label, _tip in _INDEX_DEFS:
            self._index_value_labels[key].setText("—")
            self._index_dot_labels[key].setStyleSheet(
                f"background-color: {_COLOR_NONE}; border-radius: 4px; border: none;"
            )

    def _show_and_raise(self):
        if not self.isVisible():
            self.show()
        self.raise_()

    @staticmethod
    def _format_coords(lat: float, lon: float) -> str:
        return f"Lat {lat:.5f}  •  Lon {lon:.5f}"

    @staticmethod
    def _format_value(value: Optional[float]) -> str:
        if value is None:
            return "—"
        return f"{value:.3f}"
