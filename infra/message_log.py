"""Registro das mensagens do plugin no log do QGIS, filtrado pelo nível configurado."""

from qgis.core import Qgis, QgsMessageLog

from .config.repository import ConfigRepository

# O QGIS não tem nível de depuração: o diagnóstico do plugin é registrado como Qgis.Info, e por isso DEBUG e INFO
# selecionam as mesmas mensagens.
_MINIMUM_SEVERITY = {"DEBUG": 0, "INFO": 0, "WARNING": 1, "ERROR": 2}
_SEVERITY = {Qgis.MessageLevel.Info: 0, Qgis.MessageLevel.Warning: 1, Qgis.MessageLevel.Critical: 2}


def log_message(message, tag, level=Qgis.MessageLevel.Info, notify_user=True):
    """Registra a mensagem se o nível dela alcança o configurado; níveis fora da escala contam como erro."""
    minimum = _MINIMUM_SEVERITY.get(str(ConfigRepository().get("log_level")).upper(), 0)
    if _SEVERITY.get(level, _MINIMUM_SEVERITY["ERROR"]) >= minimum:
        QgsMessageLog.logMessage(message, tag, level, notify_user)
