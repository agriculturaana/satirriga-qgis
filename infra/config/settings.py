import configparser
import os

PLUGIN_NAME = "SatIrriga"


def _published_version():
    # A versão vem do metadata.txt, o mesmo arquivo que o QGIS exige para carregar o plugin e que o release
    # atualiza; uma cópia no código fica defasada a cada versão publicada.
    metadata = configparser.ConfigParser(interpolation=None)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "metadata.txt")
    with open(path, encoding="utf-8") as stream:
        metadata.read_file(stream)
    return metadata.get("general", "version")


PLUGIN_VERSION = _published_version()

DEFAULTS = {
    "api_base_url": "https://satirriga.snirh.gov.br/api",
    "sso_base_url": "https://sso.snirh.gov.br",
    "sso_realm": "ana",
    "sso_client_id": "sat-irriga-plugin",
    "sso_resource_id": "sat-irriga",
    "environment": "production",
    "gpkg_base_dir": "",
    "page_size": 15,
    "polling_interval_ms": 3000,
    "auto_zoom_on_load": True,
    "log_level": "INFO",
}

ENVIRONMENT_COLORS = {
    "production": "#4CAF50",
    "staging": "#FF9800",
    "development": "#F44336",
}

ENVIRONMENT_LABELS = {
    "production": "PRD",
    "staging": "STG",
    "development": "DEV",
}

SETTINGS_NAMESPACE = "SatIrriga"
AUTH_NAMESPACE = "SatIrriga/auth"
