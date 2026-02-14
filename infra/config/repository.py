from qgis.core import QgsSettings

from .settings import DEFAULTS, SETTINGS_NAMESPACE


class ConfigRepository:
    """Persiste configuracoes do plugin via QgsSettings."""

    def __init__(self):
        self._settings = QgsSettings()
        self._prefix = f"{SETTINGS_NAMESPACE}/"

    def _key(self, name):
        return f"{self._prefix}{name}"

    def get(self, name):
        default = DEFAULTS.get(name)
        value = self._settings.value(self._key(name), default)
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(value)
            except (ValueError, TypeError):
                return default
        return value

    def set(self, name, value):
        self._settings.setValue(self._key(name), value)

    def get_all(self):
        return {key: self.get(key) for key in DEFAULTS}

    def restore_defaults(self):
        for key, value in DEFAULTS.items():
            self.set(key, value)
