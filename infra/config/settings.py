PLUGIN_NAME = "SatIrriga"
PLUGIN_VERSION = "2.0.0"

DEFAULTS = {
    "api_base_url": "https://satirriga.snirh.gov.br/api",
    "sso_base_url": "https://sso.snirh.gov.br",
    "sso_realm": "ana",
    "sso_client_id": "sat-irriga-plugin",
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
