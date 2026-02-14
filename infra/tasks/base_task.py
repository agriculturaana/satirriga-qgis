"""Base para tasks assincronas do SatIrriga."""

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsTask, QgsMessageLog, Qgis

from ..config.settings import PLUGIN_NAME


class TaskSignals(QObject):
    """Bridge de signals para comunicacao entre QgsTask e main thread."""
    progress_changed = pyqtSignal(int)          # 0-100
    status_message = pyqtSignal(str)            # mensagem de progresso
    completed = pyqtSignal(bool, str)           # (success, message)


class SatIrrigaTask(QgsTask):
    """Base class para tasks do plugin."""

    def __init__(self, description):
        super().__init__(description, QgsTask.CanCancel)
        self.signals = TaskSignals()
        self._exception = None

    def _log(self, message, level=Qgis.Info):
        QgsMessageLog.logMessage(message, PLUGIN_NAME, level)

    def run(self):
        """Implementar nas subclasses. Roda em worker thread."""
        raise NotImplementedError

    def finished(self, result):
        """Roda na main thread apos conclusao do run()."""
        if result:
            self.signals.completed.emit(True, "Concluido com sucesso")
        else:
            msg = str(self._exception) if self._exception else "Erro desconhecido"
            self.signals.completed.emit(False, msg)
