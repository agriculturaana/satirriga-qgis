"""Widget de progresso de upload zonal."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton,
)

from ...domain.models.enums import UploadBatchStatusEnum


class UploadProgressWidget(QWidget):
    """Mostra progresso de upload zonal com detalhes do batch."""

    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._batch_uuid = None
        self._build_ui()
        self.setVisible(False)

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Header
        self._header_label = QLabel("Upload Zonal")
        self._header_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self._header_label)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # Status label
        self._status_label = QLabel("Aguardando...")
        self._status_label.setStyleSheet("font-size: 11px; color: #616161;")
        layout.addWidget(self._status_label)

        # Detalhes
        self._detail_label = QLabel("")
        self._detail_label.setStyleSheet("font-size: 10px; color: #9E9E9E;")
        self._detail_label.setWordWrap(True)
        layout.addWidget(self._detail_label)

        # Botao cancelar
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setFixedWidth(80)
        self._cancel_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "border: none; padding: 4px 8px; border-radius: 3px; font-size: 11px; }"
            "QPushButton:hover { background-color: #D32F2F; }"
        )
        self._cancel_btn.clicked.connect(self.cancelled.emit)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        self.setStyleSheet(
            "UploadProgressWidget { "
            "background-color: #F5F5F5; border: 1px solid #E0E0E0; "
            "border-radius: 4px; }"
        )

    @property
    def batch_uuid(self):
        return self._batch_uuid

    @batch_uuid.setter
    def batch_uuid(self, value):
        self._batch_uuid = value

    def update_from_status(self, status_data: dict):
        """Atualiza todos os widgets a partir do status do batch."""
        self._batch_uuid = status_data.get("batchUuid", self._batch_uuid)

        progress = status_data.get("progressPct", 0)
        self._progress_bar.setValue(progress)

        status = status_data.get("status", "")
        try:
            status_enum = UploadBatchStatusEnum(status)
            self._status_label.setText(status_enum.label)

            if status_enum.is_terminal:
                self._cancel_btn.setEnabled(False)
                if status_enum == UploadBatchStatusEnum.COMPLETED:
                    self._status_label.setStyleSheet("font-size: 11px; color: #4CAF50;")
                elif status_enum == UploadBatchStatusEnum.FAILED:
                    self._status_label.setStyleSheet("font-size: 11px; color: #F44336;")
                else:
                    self._status_label.setStyleSheet("font-size: 11px; color: #9E9E9E;")
            else:
                self._cancel_btn.setEnabled(True)
                self._status_label.setStyleSheet("font-size: 11px; color: #616161;")
        except ValueError:
            self._status_label.setText(status)

        # Detalhes
        parts = []
        feature_count = status_data.get("featureCount", 0)
        valid_count = status_data.get("validCount", 0)
        modified_count = status_data.get("modifiedCount", 0)
        new_count = status_data.get("newCount", 0)

        if feature_count:
            parts.append(f"Features: {feature_count}")
        if valid_count:
            parts.append(f"Validas: {valid_count}")
        if modified_count:
            parts.append(f"Modificadas: {modified_count}")
        if new_count:
            parts.append(f"Novas: {new_count}")

        self._detail_label.setText(" | ".join(parts) if parts else "")

    def start_upload(self, zonal_id, batch_uuid=None):
        """Inicializa widget para novo upload."""
        self._batch_uuid = batch_uuid
        self._header_label.setText(f"Upload Zonal {zonal_id}")
        self._progress_bar.setValue(0)
        self._status_label.setText("Iniciando upload...")
        self._status_label.setStyleSheet("font-size: 11px; color: #616161;")
        self._detail_label.setText("")
        self._cancel_btn.setEnabled(True)
        self.setVisible(True)

    def finish(self):
        """Esconde widget apos conclusao."""
        self.setVisible(False)
