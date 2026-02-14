# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SatIrriga QGIS Cliente v2 — Plugin QGIS 3.22+ para o sistema SatIrriga. Workflow completo: autenticacao SSO (Keycloak OIDC PKCE), listagem de mapeamentos, download de classificacoes como GeoPackage editavel, edicao de geometrias, e envio de alteracoes ao servidor.

## Build & Development Commands

```bash
# Compile Qt resources (resources.qrc -> resources.py)
make compile

# Deploy plugin to local QGIS plugins directory
make deploy

# Run all tests (pytest)
make test

# Run unit tests only
make test-unit

# Lint
make pylint

# Create distribution zip (uses git archive)
make package VERSION=v2.0.0

# Translation workflow
make transup      # Extract new strings
make transcompile # Compile .ts -> .qm

# Clean generated files
make clean

# Remove deployed plugin
make derase
```

Local deploy path: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/satirriga_cliente/`

## Architecture (Clean Architecture + Layers)

```
UI Layer           -> ui/dock.py, ui/widgets/*
Application Layer  -> app/controllers/*, app/state/store.py
Domain Layer       -> domain/models/*, domain/services/*
Infrastructure     -> infra/http/*, infra/auth/*, infra/config/*, infra/tasks/*
```

Dependencies point inward: UI -> App -> Domain <- Infra.

### Plugin Lifecycle

`__init__.py::classFactory(iface)` -> `plugin.SatIrrigaPlugin` (controller) -> manages `SatIrrigaDock` (view with tabs).

QGIS calls `initGui()` on load, `unload()` on removal, and `run()` on user activation.

### Key Files

| File/Dir | Role |
|----------|------|
| `plugin.py` | Plugin controller (initGui/unload/run + DI wiring) |
| `ui/dock.py` | Main dock with QTabWidget (5 tabs) |
| `ui/widgets/` | Tab widgets (mapeamentos, camadas, config, sessao, logs) |
| `app/state/store.py` | AppState (centralized state with pyqtSignals) |
| `app/controllers/` | Auth, Mapeamento, Config controllers |
| `domain/models/` | Dataclasses (Mapeamento, Metodo, Zonal, UserInfo, enums) |
| `domain/services/` | Business logic (mapeamento_service, gpkg_service) |
| `infra/http/` | HttpClient (QgsNetworkAccessManager), AuthInterceptor |
| `infra/auth/` | OIDC PKCE flow, TokenStore, SessionManager |
| `infra/config/` | Settings defaults, ConfigRepository (QgsSettings) |
| `infra/tasks/` | QgsTask subclasses (download, upload) |
| `satirriga_cliente.py` | **LEGACY v1** — kept for reference, not imported |

### Key Dependencies

- **PyQt5** — UI framework (QDockWidget, signals/slots, QTabWidget)
- **qgis.core** — QgsProject, QgsRasterLayer, QgsVectorLayer, QgsTask, QgsNetworkAccessManager
- **qgis.PyQt** — Qt bindings provided by QGIS

### Test Structure

Tests use `pytest` + `pytest-qt`. Structure:
- `tests/unit/domain/` — models, parsers, business rules (no QGIS dependency)
- `tests/unit/infra/` — HTTP, auth, config
- `tests/unit/app/` — controllers, state
- `tests/integration/` — GPKG roundtrip
- `tests/fixtures/` — JSON responses, sample ZIPs
