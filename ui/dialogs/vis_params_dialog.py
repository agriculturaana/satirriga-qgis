"""Dialogo de customizacao de parametros de visualizacao raster."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QDoubleSpinBox, QComboBox, QPushButton,
    QGroupBox, QDialogButtonBox,
)

from ...domain.models.raster import VisParams
from ...domain.services.raster_service import (
    AVAILABLE_PALETTES, get_default_vis_params,
)


class VisParamsDialog(QDialog):
    """Dialogo para ajustar parametros de visualizacao de camadas raster XYZ."""

    def __init__(self, vis_params: VisParams, parent=None):
        super().__init__(parent)
        self._original_params = vis_params
        self._band = vis_params.band
        self.setWindowTitle("Ajustar Visualização")
        self.setMinimumWidth(360)
        self._build_ui(vis_params)

    def _build_ui(self, params: VisParams):
        layout = QVBoxLayout(self)

        # Banda (somente leitura)
        band_label = QLabel(f"<b>Banda:</b> {params.band}")
        layout.addWidget(band_label)

        # Escala
        scale_group = QGroupBox("Escala")
        scale_form = QFormLayout(scale_group)

        self._spin_min = QDoubleSpinBox()
        self._spin_min.setRange(-10000, 10000)
        self._spin_min.setDecimals(2)
        self._spin_min.setValue(params.min_val if params.min_val is not None else 0)
        scale_form.addRow("Mínimo:", self._spin_min)

        self._spin_max = QDoubleSpinBox()
        self._spin_max.setRange(-10000, 10000)
        self._spin_max.setDecimals(2)
        self._spin_max.setValue(params.max_val if params.max_val is not None else 1)
        scale_form.addRow("Máximo:", self._spin_max)

        layout.addWidget(scale_group)

        # Ajustes
        adjust_group = QGroupBox("Ajustes")
        adjust_form = QFormLayout(adjust_group)

        self._spin_gamma = QDoubleSpinBox()
        self._spin_gamma.setRange(0.1, 5.0)
        self._spin_gamma.setSingleStep(0.1)
        self._spin_gamma.setDecimals(2)
        self._spin_gamma.setValue(params.gamma if params.gamma is not None else 1.0)
        adjust_form.addRow("Gamma:", self._spin_gamma)

        layout.addWidget(adjust_group)

        # Paleta
        palette_group = QGroupBox("Paleta")
        palette_layout = QVBoxLayout(palette_group)

        self._combo_palette = QComboBox()
        self._combo_palette.addItem("(nenhuma)", "")

        # Separador: Especificas
        self._combo_palette.insertSeparator(self._combo_palette.count())
        domain_palettes = AVAILABLE_PALETTES[:5]
        generic_palettes = AVAILABLE_PALETTES[5:]

        for key, label in domain_palettes:
            self._combo_palette.addItem(label, key)

        # Separador: Genericas
        self._combo_palette.insertSeparator(self._combo_palette.count())
        for key, label in generic_palettes:
            self._combo_palette.addItem(label, key)

        # Seleciona paleta atual
        if params.palette:
            idx = self._combo_palette.findData(params.palette)
            if idx >= 0:
                self._combo_palette.setCurrentIndex(idx)

        palette_layout.addWidget(self._combo_palette)
        layout.addWidget(palette_group)

        # Botoes
        btn_layout = QHBoxLayout()

        btn_restore = QPushButton("Restaurar padrão")
        btn_restore.clicked.connect(self._restore_defaults)
        btn_layout.addWidget(btn_restore)

        btn_layout.addStretch()

        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        btn_layout.addWidget(button_box)

        layout.addLayout(btn_layout)

    def _restore_defaults(self):
        """Restaura valores padrao da banda."""
        defaults = get_default_vis_params(self._band)
        self._spin_min.setValue(defaults.min_val if defaults.min_val is not None else 0)
        self._spin_max.setValue(defaults.max_val if defaults.max_val is not None else 1)
        self._spin_gamma.setValue(defaults.gamma if defaults.gamma is not None else 1.0)
        if defaults.palette:
            idx = self._combo_palette.findData(defaults.palette)
            if idx >= 0:
                self._combo_palette.setCurrentIndex(idx)
        else:
            self._combo_palette.setCurrentIndex(0)

    def get_params(self) -> VisParams:
        """Retorna VisParams com os valores atuais do dialogo.

        Preserva gain/bias do VisParams original, pois nao sao editaveis
        neste dialogo.
        """
        palette = self._combo_palette.currentData() or None
        gamma_val = self._spin_gamma.value()
        return VisParams(
            band=self._band,
            min_val=self._spin_min.value(),
            max_val=self._spin_max.value(),
            gamma=gamma_val if gamma_val != 1.0 or self._band == "original" else None,
            palette=palette,
            gain=self._original_params.gain,
            bias=self._original_params.bias,
        )
