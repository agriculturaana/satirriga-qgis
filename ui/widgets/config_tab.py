"""Aba de configuracoes do plugin."""

import os

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QCheckBox, QPushButton, QHBoxLayout, QLabel,
    QFileDialog, QMessageBox, QDoubleSpinBox, QGroupBox,
    QScrollArea,
)

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)

from ...infra.config.settings import DEFAULTS
from ..theme import SectionHeader
from ..icon_utils import tinted_icon


class ConfigTab(QWidget):
    """Formulario de configuracoes do plugin."""

    def __init__(self, config_controller, parent=None):
        super().__init__(parent)
        self._controller = config_controller
        self._fields = {}

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)

        section_header = SectionHeader("Configurações")
        layout.addWidget(section_header)

        form = QFormLayout()

        # API Base URL
        self._fields["api_base_url"] = QLineEdit()
        form.addRow("API Base URL:", self._fields["api_base_url"])

        # SSO Base URL
        self._fields["sso_base_url"] = QLineEdit()
        form.addRow("SSO Base URL:", self._fields["sso_base_url"])

        # SSO Realm
        self._fields["sso_realm"] = QLineEdit()
        form.addRow("SSO Realm:", self._fields["sso_realm"])

        # SSO Client ID
        self._fields["sso_client_id"] = QLineEdit()
        form.addRow("SSO Client ID:", self._fields["sso_client_id"])

        # Environment
        self._fields["environment"] = QComboBox()
        self._fields["environment"].addItems(["production", "staging", "development"])
        form.addRow("Ambiente:", self._fields["environment"])

        # GPKG Base Dir
        gpkg_layout = QHBoxLayout()
        self._fields["gpkg_base_dir"] = QLineEdit()
        self._fields["gpkg_base_dir"].setPlaceholderText("(auto)")
        gpkg_layout.addWidget(self._fields["gpkg_base_dir"])
        browse_btn = QPushButton(QIcon(os.path.join(_ICONS_DIR, "action_folder.svg")), "")
        browse_btn.setIconSize(QSize(16, 16))
        browse_btn.setFixedWidth(30)
        browse_btn.setToolTip("Selecionar diretório para armazenamento de GeoPackages")
        browse_btn.clicked.connect(self._browse_gpkg_dir)
        gpkg_layout.addWidget(browse_btn)
        form.addRow("Diretório GPKG:", gpkg_layout)

        # Page Size
        self._fields["page_size"] = QSpinBox()
        self._fields["page_size"].setRange(5, 100)
        form.addRow("Itens por página:", self._fields["page_size"])

        # Polling Interval
        self._fields["polling_interval_ms"] = QSpinBox()
        self._fields["polling_interval_ms"].setRange(1000, 30000)
        self._fields["polling_interval_ms"].setSingleStep(1000)
        self._fields["polling_interval_ms"].setSuffix(" ms")
        form.addRow("Polling interval:", self._fields["polling_interval_ms"])

        # Auto zoom
        self._fields["auto_zoom_on_load"] = QCheckBox("Zoom automático ao carregar camada")
        form.addRow("", self._fields["auto_zoom_on_load"])

        # Log level
        self._fields["log_level"] = QComboBox()
        self._fields["log_level"].addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        form.addRow("Log level:", self._fields["log_level"])

        layout.addLayout(form)

        # --- Visualização de Rasters ---
        vis_header = SectionHeader("Visualização de Imagens", "defaults por banda")
        layout.addWidget(vis_header)

        self._vis_widgets = {}
        self._build_vis_config(layout)

        layout.addStretch()

        # Status label
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("font-size: 11px;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # Botoes
        btn_layout = QHBoxLayout()

        save_btn = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_save.svg"), "#FFFFFF"), "Salvar")
        save_btn.setIconSize(QSize(16, 16))
        save_btn.setToolTip("Salvar todas as configurações")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border-radius: 4px; padding: 6px 16px; }"
        )
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        restore_btn = QPushButton(QIcon(os.path.join(_ICONS_DIR, "action_rotate_cw.svg")), "Restaurar Defaults")
        restore_btn.setIconSize(QSize(16, 16))
        restore_btn.setToolTip("Restaurar todas as configurações para os valores padrão")
        restore_btn.clicked.connect(self._on_restore)
        btn_layout.addWidget(restore_btn)

        test_btn = QPushButton(QIcon(os.path.join(_ICONS_DIR, "action_wifi.svg")), "Testar Conexão")
        test_btn.setIconSize(QSize(16, 16))
        test_btn.setToolTip("Testar conexão com o servidor da API")
        test_btn.clicked.connect(self._on_test)
        btn_layout.addWidget(test_btn)

        layout.addLayout(btn_layout)

        inner.setLayout(layout)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.setLayout(outer)

    def _build_vis_config(self, parent_layout):
        """Constrói controles de configuração de visualização por banda."""
        from ...domain.services.vis_config_service import (
            CONFIGURABLE_BANDS, get_global_vis_params,
        )
        from ...domain.services.raster_service import AVAILABLE_PALETTES

        for band_key, band_label in CONFIGURABLE_BANDS:
            group = QGroupBox(band_label)
            group.setStyleSheet(
                "QGroupBox { font-size: 11px; font-weight: bold; "
                "border: 1px solid #455A64; border-radius: 4px; "
                "margin-top: 6px; padding-top: 14px; }"
                "QGroupBox::title { subcontrol-position: top left; padding: 2px 6px; }"
            )
            form = QFormLayout()
            form.setContentsMargins(6, 2, 6, 4)
            form.setSpacing(2)

            params = get_global_vis_params(band_key)

            min_spin = QDoubleSpinBox()
            min_spin.setRange(-10000, 10000)
            min_spin.setDecimals(2)
            min_spin.setValue(params.min_val if params.min_val is not None else 0)
            form.addRow("Min:", min_spin)

            max_spin = QDoubleSpinBox()
            max_spin.setRange(-10000, 10000)
            max_spin.setDecimals(2)
            max_spin.setValue(params.max_val if params.max_val is not None else 1)
            form.addRow("Max:", max_spin)

            gamma_spin = QDoubleSpinBox()
            gamma_spin.setRange(0.1, 5.0)
            gamma_spin.setSingleStep(0.1)
            gamma_spin.setDecimals(2)
            gamma_spin.setValue(params.gamma if params.gamma is not None else 1.0)
            form.addRow("Gamma:", gamma_spin)

            palette_combo = QComboBox()
            palette_combo.addItem("(nenhuma)", "")
            for pal_key, pal_label in AVAILABLE_PALETTES:
                palette_combo.addItem(pal_label, pal_key)
            if params.palette:
                idx = palette_combo.findData(params.palette)
                if idx >= 0:
                    palette_combo.setCurrentIndex(idx)
            form.addRow("Paleta:", palette_combo)

            group.setLayout(form)
            parent_layout.addWidget(group)

            self._vis_widgets[band_key] = {
                "min": min_spin,
                "max": max_spin,
                "gamma": gamma_spin,
                "palette": palette_combo,
            }

    def _save_vis_config(self):
        """Salva configuração de visualização para QgsSettings."""
        from ...domain.models.raster import VisParams
        from ...domain.services.vis_config_service import save_global_vis_params
        from qgis.core import QgsMessageLog, Qgis

        for band_key, widgets in self._vis_widgets.items():
            palette_val = widgets["palette"].currentData()
            params = VisParams(
                band=band_key,
                min_val=widgets["min"].value(),
                max_val=widgets["max"].value(),
                gamma=widgets["gamma"].value(),
                palette=palette_val or None,
            )
            save_global_vis_params(band_key, params)
            QgsMessageLog.logMessage(
                f"[VisConfig] Salvo {band_key}: min={params.min_val} max={params.max_val} "
                f"gamma={params.gamma} palette={params.palette}",
                "SatIrriga", Qgis.Info,
            )

    def _load_vis_config(self):
        """Carrega configuração de visualização de QgsSettings."""
        from ...domain.services.vis_config_service import get_global_vis_params

        for band_key, widgets in self._vis_widgets.items():
            params = get_global_vis_params(band_key)
            widgets["min"].setValue(params.min_val if params.min_val is not None else 0)
            widgets["max"].setValue(params.max_val if params.max_val is not None else 1)
            widgets["gamma"].setValue(params.gamma if params.gamma is not None else 1.0)
            if params.palette:
                idx = widgets["palette"].findData(params.palette)
                if idx >= 0:
                    widgets["palette"].setCurrentIndex(idx)
            else:
                widgets["palette"].setCurrentIndex(0)

    def _load_values(self):
        values = self._controller.get_all()
        for key, widget in self._fields.items():
            val = values.get(key, DEFAULTS.get(key))
            if isinstance(widget, QLineEdit):
                widget.setText(str(val) if val else "")
            elif isinstance(widget, QComboBox):
                idx = widget.findText(str(val))
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(val) if val else 0)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(val))

    def _collect_values(self):
        values = {}
        for key, widget in self._fields.items():
            if isinstance(widget, QLineEdit):
                values[key] = widget.text().strip()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentText()
            elif isinstance(widget, QSpinBox):
                values[key] = widget.value()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
        return values

    def _browse_gpkg_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Selecionar diretório para GeoPackages"
        )
        if directory:
            self._fields["gpkg_base_dir"].setText(directory)

    def _show_status(self, message, is_error=False):
        self._status_label.setText(message)
        color = "#F44336" if is_error else "#4CAF50"
        self._status_label.setStyleSheet(f"font-size: 11px; color: {color};")
        self._status_label.setVisible(True)

    def _on_save(self):
        values = self._collect_values()
        self._controller.save(values)
        try:
            self._save_vis_config()
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                f"[Config] Erro ao salvar vis config: {e}",
                "SatIrriga", Qgis.Warning,
            )
        self._show_status("Configurações salvas com sucesso!")

    def _on_restore(self):
        self._controller.restore_defaults()
        from ...domain.services.vis_config_service import restore_global_defaults
        restore_global_defaults()
        self._load_values()
        self._load_vis_config()
        self._show_status("Defaults restaurados!")

    def _on_test(self):
        self._show_status("Testando conexao...")
        self._controller.test_connection(self._on_test_result)

    def _on_test_result(self, success, message):
        self._show_status(message, is_error=not success)
