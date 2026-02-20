# Changelog

Todas as mudancas notaveis do SatIrriga QGIS Plugin serao documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [2.1.0] - 2026-02-19

### Adicionado

- **Fluxo Zonal V2 (Feature Server):** novo workflow completo de download/upload centrado em zonal, substituindo o fluxo V1 baseado em mapeamento/metodo (SHP ZIP)
- **Checkout + FlatGeobuf:** download via `POST /zonal/{id}/checkout` com edit token + `GET /zonal/{id}/features` em formato FlatGeobuf, com suporte a cache condicional via ETag
- **Upload assincrono com polling:** envio via `POST /zonal/{id}/upload` (HTTP 202) com polling de status do batch, progresso em tempo real na UI e suporte a deteccao de conflitos
- **Catalogo Zonal:** nova aba na tela de Mapeamentos com toggle "Mapeamentos / Catalogo Zonal" para listar zonais CONSOLIDATED/DONE disponiveis para download
- **Widget de progresso de upload:** componente visual na aba Camadas exibindo barra de progresso, status textual do batch, contagem de features e botao de cancelamento
- **Resolucao de conflitos (P2):** dialog interativo para resolver conflitos feature-a-feature durante upload, com opcoes "Minha versao", "Versao servidor" e "Merge", incluindo acoes em lote
- **Sidecar `.satirriga.json`:** arquivo de metadados ao lado do GPKG V2 contendo edit token, versao do zonal, snapshot hash, ETag e timestamps
- **Deteccao de features novas:** edit tracking agora captura `addedFeatures()` do editBuffer e marca com `_sync_status = NEW`
- **Modelos de dominio V2:** `CatalogoItem`, `UploadBatchStatus`, `ConflictItem`, `ConflictSet`
- **Enums V2:** `ZonalStatusEnum` (7 estados), `UploadBatchStatusEnum` (12 estados com `is_terminal`), `ConflictResolutionEnum`
- **41 novos testes unitarios** cobrindo modelos V2, enums, sidecar, paths zonais, listagem dual V1/V2 e estado do catalogo

### Alterado

- `DownloadClassificationTask` reescrita como `DownloadZonalTask` (checkout + FlatGeobuf -> GPKG com campos V2)
- `UploadClassificationTask` reescrita como `UploadZonalTask` (export todas features + POST 202 + polling assincrono)
- `list_local_gpkgs()` agora detecta GPKGs V1 (`mapeamento_X/metodo_Y.gpkg`) e V2 (`zonal_X/zonal_X.gpkg`) com campos `type`, `zonal_id`, `has_sidecar`
- `count_features_by_sync_status()` agora inclui contagem de `NEW` no retorno
- `connect_edit_tracking()` aceita contexto V2 (`zonal_id`) alem de V1 (`mapeamento_id`, `metodo_id`)
- `AppState` ampliado com signals `catalogo_changed`, `upload_progress_changed`, `conflict_detected`, `upload_batch_completed` e property `catalogo_items`
- Aba Camadas exibe GPKGs V1 e V2 lado a lado com indicadores visuais diferenciados
- Badge de camadas modificadas agora soma MODIFIED + NEW

### Deprecado

- Fluxo V1 de download (`download_classification`) — endpoints antigos nao existem mais no backend
- Fluxo V1 de upload (`upload_classification`) — botao "Enviar" desabilitado para GPKGs legados com tooltip orientando re-download via Catalogo
- Botao "Baixar" na mini-tabela de metodos substituido por label "Use Catalogo"

### Compatibilidade

- GPKGs V1 existentes continuam visiveis e podem ser abertos na aba Camadas (somente leitura)
- Download e upload so funcionam via novo fluxo zonal V2

## [2.0.0] - 2026-02-14

### Adicionado

- Reescrita completa do plugin em Clean Architecture (UI -> App -> Domain <- Infra)
- Autenticacao SSO via Keycloak OIDC PKCE com restauracao automatica de sessao
- Activity bar com navegacao por icones (Home, Mapeamentos, Camadas, Config, Logs)
- Tela Home com logos institucionais ANA/INPE e navegacao condicional por auth
- Listagem paginada de mapeamentos com busca, ordenacao server-side e detalhe expandivel
- Mini-tabela de metodos com status colorido e polling automatico para PROCESSING
- Download de classificacoes SHP ZIP com conversao automatica para GeoPackage editavel
- Upload de features modificadas via POST multipart
- Edit tracking automatico com `beforeCommitChanges`/`afterCommitChanges`
- Campos de sync (`_original_fid`, `_sync_status`, `_sync_timestamp`, `_mapeamento_id`, `_metodo_id`)
- Aba de camadas locais com status de sync colorido e acoes (Abrir, Enviar, Remover)
- Aba de configuracoes (URL API, URL SSO, diretorio GPKG, page size, auto-zoom)
- Aba de logs integrada ao QgsMessageLog
- HttpClient sobre QgsNetworkAccessManager com AuthInterceptor
- Pagina de callback OIDC com visual customizado
- Suite de 83 testes unitarios (domain, infra, app)
- Internacionalizacao (i18n) preparada com QTranslator
- Makefile com targets: compile, deploy, test, lint, package, clean

### Removido

- Codigo legado do plugin v1 (`satirriga_cliente.py`, `satirriga_cliente_dockwidget.py`)
- Dependencia de `.ui` files (UI construida programaticamente)

## [1.0.0] - 2024-10-30

### Adicionado

- Versao inicial do plugin gerada via QGIS Plugin Builder
- Autenticacao basica com Keycloak (login/logout)
- Listagem de mapeamentos do SatIrriga
- Visualizacao de metodos de mapeamento com selecao
- Download de classificacoes como camada vetorial
- Interface via QDockWidget com abas (Login, Mapeamentos, Metodos, Visualizar)
- Barra de progresso para downloads
- Suporte a proxy configurado no QGIS
- Carregamento de camadas raster (COG) e vetorial no projeto
