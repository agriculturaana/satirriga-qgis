"""Aba de configuracoes do plugin."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QCheckBox, QPushButton, QHBoxLayout, QLabel,
    QFileDialog, QMessageBox,
)

from ...infra.config.settings import DEFAULTS


class ConfigTab(QWidget):
    """Formulario de configuracoes do plugin."""

    def __init__(self, config_controller, parent=None):
        super().__init__(parent)
        self._controller = config_controller
        self._fields = {}

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)

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
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self._browse_gpkg_dir)
        gpkg_layout.addWidget(browse_btn)
        form.addRow("Diretorio GPKG:", gpkg_layout)

        # Page Size
        self._fields["page_size"] = QSpinBox()
        self._fields["page_size"].setRange(5, 100)
        form.addRow("Itens por pagina:", self._fields["page_size"])

        # Polling Interval
        self._fields["polling_interval_ms"] = QSpinBox()
        self._fields["polling_interval_ms"].setRange(1000, 30000)
        self._fields["polling_interval_ms"].setSingleStep(1000)
        self._fields["polling_interval_ms"].setSuffix(" ms")
        form.addRow("Polling interval:", self._fields["polling_interval_ms"])

        # Auto zoom
        self._fields["auto_zoom_on_load"] = QCheckBox("Zoom automatico ao carregar camada")
        form.addRow("", self._fields["auto_zoom_on_load"])

        # Log level
        self._fields["log_level"] = QComboBox()
        self._fields["log_level"].addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        form.addRow("Log level:", self._fields["log_level"])

        layout.addLayout(form)
        layout.addStretch()

        # Status label
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("font-size: 11px;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # Botoes
        btn_layout = QHBoxLayout()

        save_btn = QPushButton("Salvar")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border-radius: 4px; padding: 6px 16px; }"
        )
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        restore_btn = QPushButton("Restaurar Defaults")
        restore_btn.clicked.connect(self._on_restore)
        btn_layout.addWidget(restore_btn)

        test_btn = QPushButton("Testar Conexao")
        test_btn.clicked.connect(self._on_test)
        btn_layout.addWidget(test_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

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
            self, "Selecionar diretorio para GeoPackages"
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
        self._show_status("Configuracoes salvas com sucesso!")

    def _on_restore(self):
        self._controller.restore_defaults()
        self._load_values()
        self._show_status("Defaults restaurados!")

    def _on_test(self):
        self._show_status("Testando conexao...")
        self._controller.test_connection(self._on_test_result)

    def _on_test_result(self, success, message):
        self._show_status(message, is_error=not success)
