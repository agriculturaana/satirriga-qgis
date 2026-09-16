"""Widget de progresso de upload zonal."""

import os

from qgis.PyQt.QtCore import Qt, QSize, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton,
)

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)
from ..icon_utils import tinted_icon

from ...domain.models.enums import UploadBatchStatusEnum, ZonalStatusEnum
from ...domain.services.upload_feedback import reprocessing_outcome, summarize_batch


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
        self._progress_bar.setToolTip("Progresso do envio ao servidor")
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
        self._cancel_btn = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_ban.svg"), "#FFFFFF"), "Cancelar")
        self._cancel_btn.setIconSize(QSize(14, 14))
        self._cancel_btn.setFixedWidth(90)
        self._cancel_btn.setToolTip("Cancelar envio em andamento")
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
        phase = status_data.get("phase", "upload")
        self._batch_uuid = status_data.get("batchUuid", self._batch_uuid)

        # Fase de reprocessamento (overlay + zonal stats)
        if phase == "reprocessing":
            zonal_status = status_data.get("zonalStatus", "PROCESSING")
            self._cancel_btn.setEnabled(False)
            self._progress_bar.setRange(0, 0)  # indeterminada
            self._status_label.setText(
                "Recalculando overlay e estatísticas zonais..."
            )
            self._status_label.setStyleSheet("font-size: 11px; color: #2196F3;")
            try:
                status_enum = ZonalStatusEnum(zonal_status)
                detail = f"Status: {status_enum.label}"
            except ValueError:
                detail = f"Status: {zonal_status}"
            ciclos = status_data.get("overlayRetryCount") or 0
            pendentes = status_data.get("pendingGeoids") or 0
            if ciclos:
                detail += f" · ciclo adicional de overlay {ciclos}"
            if pendentes:
                detail += f" · {pendentes} feição(ões) aguardando identificador"
            self._detail_label.setText(detail)
            return

        if phase == "reprocessing_done":
            outcome = reprocessing_outcome(
                status_data.get("reprocessingStatus") or status_data.get("zonalStatus"),
                status_data.get("reprocessingError") or status_data.get("lastError"),
                status_data.get("pendingGeoids") or 0,
            )
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(100)
            self._cancel_btn.setEnabled(False)
            self._status_label.setText(outcome.label)
            self._status_label.setStyleSheet(f"font-size: 11px; color: {outcome.color};")
            self._detail_label.setText(outcome.message)
            self._detail_label.setToolTip(outcome.message)
            return

        if phase == "reprocessing_timeout":
            self._progress_bar.setRange(0, 0)
            self._cancel_btn.setEnabled(False)
            self._status_label.setText("Recálculo em andamento no servidor")
            self._status_label.setStyleSheet("font-size: 11px; color: #2196F3;")
            self._detail_label.setText(
                "O envio foi concluído. O recálculo de overlay e estatísticas "
                "continua no servidor e o mapeamento ficará disponível ao terminar; "
                "acompanhe o status na aba Mapeamentos."
            )
            return

        if phase == "upload_pending":
            self._progress_bar.setRange(0, 0)
            self._cancel_btn.setEnabled(False)
            self._status_label.setText("Envio pendente de confirmação")
            self._detail_label.setText("Retome o envio para consultar o recibo preservado desta operação.")
            return

        # Fase de upload (comportamento existente)
        self._batch_uuid = status_data.get("batchUuid", self._batch_uuid)

        progress = status_data.get("progressPct", 0)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(progress)

        status = status_data.get("status", "")
        try:
            status_enum = UploadBatchStatusEnum(status)
            self._status_label.setText(status_enum.label)

            if status_enum.is_terminal:
                self._cancel_btn.setEnabled(False)
                if status_enum == UploadBatchStatusEnum.COMPLETED:
                    self._status_label.setText("Envio persistido")
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

        # Detalhes, incluindo as feições rejeitadas pelo servidor (a versão
        # anterior é mantida quando a feição já existia)
        summary = summarize_batch(status_data)
        detail = summary.detail_text()
        rejection = summary.rejection_text()
        if rejection:
            detail = f"{detail}\n{rejection}" if detail else rejection
        self._detail_label.setText(detail)
        self._detail_label.setToolTip(rejection)

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
