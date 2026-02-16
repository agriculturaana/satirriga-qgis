# SatIrriga QGIS Plugin

QGIS desktop client for the **SatIrriga** platform — a satellite-based irrigation monitoring system developed by **ANA** (Brazil's National Water and Sanitation Agency) and **INPE** (Brazil's National Institute for Space Research).

## What it does

SatIrriga QGIS brings the full irrigation-map review workflow into the QGIS environment. Analysts and technicians can validate and correct remote-sensing classification results without switching between applications.

**Key capabilities:**

- **Secure login** — Single Sign-On through institutional credentials (Keycloak).
- **Campaign browsing** — Search, sort, and paginate through irrigation mapping campaigns.
- **Layer download** — Retrieve classification results as editable GeoPackage files.
- **Geometry editing** — Refine irrigated-area boundaries using native QGIS sketching and editing tools.
- **Data submission** — Send corrected geometries back to the SatIrriga server in a single step.

## Requirements

- QGIS **3.22** or later (Windows, macOS, or Linux)
- Institutional SSO credentials with access to the SatIrriga platform

## Installation

1. Download the latest release from the [repository](https://github.com/agriculturaana/satirriga-qgis).
2. In QGIS, go to **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the downloaded `.zip` file and click **Install**.
4. Enable **SatIrriga QGIS** in the plugin list.

Alternatively, copy the extracted plugin folder to:

```
~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/satirriga_qgis/
```

## Getting started

1. Click the **SatIrriga** icon in the QGIS toolbar. A dock panel opens on the right.
2. The **Home** screen displays the SatIrriga and institutional logos.
3. Click **Login** in the top-right corner. A browser window opens for authentication. After a successful login, the plugin navigates to the campaigns list automatically.

## Workflow

### Browsing campaigns

The **Mapeamentos** tab lists all available mapping campaigns. Use the search bar to filter by description, or click column headers to sort by date or name. Pagination controls appear at the bottom.

### Downloading layers

Select a campaign to expand its detail panel. Each classification method is listed with its processing status. When a method is marked as **Done**, click **Download** to retrieve the layer as a GeoPackage file. The layer is added to the QGIS project and grouped by campaign name.

### Editing geometries

Open the downloaded layer for editing using standard QGIS tools. The plugin tracks all modified features automatically. A badge on the **Camadas** navigation button indicates how many features have pending changes.

### Submitting changes

Open the **Camadas** tab to see all locally downloaded layers and their modification status. Submit corrected geometries back to the server with a single action.

## Configuration

Open the **Settings** tab (gear icon) to adjust:

| Option | Description |
|--------|-------------|
| API server | SatIrriga API endpoint |
| SSO server | Keycloak authentication server |
| Environment | Production, staging, or development |
| Page size | Number of campaigns per page |
| Auto-zoom | Zoom to layer extent after download |

## Frequently asked questions

**My session expired. Do I need to log in again?**
The plugin refreshes the session automatically in the background. If the refresh token has also expired, you will be prompted to log in again.

**Can I edit layers offline?**
Yes. Downloaded GeoPackage files are stored locally. You can edit them without a network connection and submit changes when connectivity is restored.

**Which satellites are supported?**
The plugin displays whatever satellite data is available on the SatIrriga server (typically Sentinel-2). Satellite coverage depends on the mapping campaign configuration.

## Support

- Issues: [github.com/agriculturaana/satirriga-qgis/issues](https://github.com/agriculturaana/satirriga-qgis/issues)
- Repository: [github.com/agriculturaana/satirriga-qgis](https://github.com/agriculturaana/satirriga-qgis)

## License

See [LICENSE](LICENSE).
