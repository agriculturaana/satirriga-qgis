# Changelog

Todas as mudancas notaveis do SatIrriga QGIS Plugin serao documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [3.1.0] - 2026-05-12

### Adicionado

- **Inspeção pontual de índices espectrais:** painel flutuante consulta NDVI, SAVI, EVI, NDWI, MNDWI e Albedo no ponto clicado, para os `image_ids` das datas expandidas na árvore de camadas; cache LRU evita requisições repetidas
- **Download de mapeamento homologado (somente leitura):** novo botão "Baixar Mapeamento Homologado" nos cards homologados da aba Homologação baixa o GeoPackage consolidado em `{base_dir}/homologacao/mapeamento_<id>/`
- **Camadas-base por viewport via GeoJSON:** carregamento sob demanda das camadas Municipios, Bacias Fiscalização e Empreendimentos a partir do bbox visível, substituindo MVT
- **Cards de Camadas Locais com método e descrição completos:** layout espelha a aba Mapeamentos (linha `data · método` + descrição com word-wrap até 3 linhas e tooltip), com `metodoApply` extraído do sidecar
- **Download direto de resultado zonal em GeoPackage:** endpoint dedicado evita conversão FGB→GPKG no cliente

### Corrigido

- **Comparação de versões com GeoPackage:** endpoint do backend migrado de `ST_AsFlatGeobuf` para `ST_AsGeoJSON + ogr2ogr→GPKG`, contornando bug do PostGIS 3.4.x (RDS) que corrompia o binário FGB quando havia muitas colunas TEXT (`Column index out of range` no parser GDAL → camada vazia no QGIS)
- **Renderer da camada de comparação:** trocado `QgsRuleBasedRenderer` (cuja root rule com símbolo padrão azul renderizava todas as features por baixo das categorias semitransparentes) por `QgsCategorizedSymbolRenderer`, agora as cores CREATED/MODIFIED/DELETED/ACCEPTED batem com a legenda
- **SIGSEGV ao registrar interceptor de tiles base no startup**
- **URL da API/SSO aplicada sem necessidade de reiniciar o QGIS**
- **Label de versão sincronizado:** `PLUGIN_VERSION` em `settings.py` estava preso em `2.1.0`; agora reflete a versão real do plugin em todos os locais que consomem a constante (header do dock, aba Home)

### Alterado

- **Paleta default do Albedo:** alterada de `HOT_R` (vermelho-laranja invertido, faixa 0.1..1.6) para `ALBEDO` (cinza preto→branco) com faixa `-0.7..0.4` (mesma do NDWI). Configurações já salvas em `QgsSettings` permanecem intocadas
- **Camada base "Bacias Hidrograficas" renomeada para "Bacias Fiscalização"** (chave interna `bacias` e endpoint preservados)
- **Removida exibição de área (ha)** dos cards das abas Mapeamentos e Homologação; mantém-se a contagem de feições

### Compatibilidade

- GeoPackages baixados antes desta versão sem `metodoApply` no sidecar exibem `—` no campo de método; rebaixar restaura o valor
- Endpoint de comparação `/api/zonal/:id/compare` agora serve `Content-Type: application/geopackage+sqlite3` (era `application/flatgeobuf`); requer backend ≥ correspondente

## [3.0.0] - 2026-04-15

### Adicionado

- **Aba de Homologação:** fluxo completo de revisão técnica com emissão de parecer (aprovar/reprovar/devolver/cancelar), suprimir mapeamento, filtros por status (Aguardando, Homologados, Reprovados, Cancelados), ordenação e paginação server-side, e download somente leitura das camadas do zonal para inspeção visual
- **Histórico de envios:** nova aba com cards por batch (status, métricas, versionamento) e comparação visual entre versões, com zoom automático na extensão combinada das camadas carregadas
- **Hierarquia de camadas raster:** árvore Datas → Bandas → Cenas agrupando tiles Sentinel-2 por data de aquisição, com bandas RGB, NDVI, NDWI e Albedo segregadas em grupos
- **Camadas de diferença (NDVI/NDWI/albedo):** URLs `operator=SUBTRACT` já prontas do servidor indexadas na data da primeira imagem do par, deduplicadas por URL, com paletas específicas (SPECTRAL para NDVI/NDWI, COOLWARM para albedo)
- **Downloads segregados por origem:** Mapeamentos e Homologação são gravados em diretórios distintos e carregados em grupos separados na árvore de camadas, permitindo coexistência do mesmo zonal em ambos os fluxos
- **Reprocessamento de overlay:** botão dedicado para zonais com falha em estatísticas zonais, com polling de status e feedback inline
- **Encerramento de mapeamento:** ação na aba de homologação que finaliza o ciclo de um mapeamento
- **Progresso inline por zonal:** label dinâmica nos cards reflete transições em tempo real (`PROCESSING` → `OVERLAID` → `CONSOLIDATED`)
- **Polling contínuo de status:** sem cache local, o badge do zonal acompanha o estado real retornado pela API, encerrando automaticamente ao atingir status terminal
- **Renovação automática de editToken:** re-checkout disparado antes da expiração para evitar falhas em uploads longos
- **Ordenação server-side no catálogo:** combobox de ordenação com direção ascendente/descendente
- **Requisitos de homologação:** validação do papel `homologar` antes de permitir ações restritas
- **Diálogo de parecer:** dialog dedicado com validação de tamanho mínimo do motivo

### Corrigido

- **Detecção de novas geometrias para sincronização:** features recém-criadas agora são marcadas corretamente como `NEW` e incluídas no batch de envio
- **Conversão FlatGeobuf resiliente a erros de parse por feature:** features inválidas são registradas e puladas sem abortar o download inteiro
- **Atualização de status dos cards de zonal:** removido cache local que impedia o badge de refletir a transição real retornada pela API; eliminado ciclo render → recache → piscar
- **Máscara ROI acima dos polígonos da zonal:** borda tracejada de referência agora é sempre visível, posicionada no topo do grupo
- **Download somente leitura na aba de homologação:** homologador visualiza sem disparar checkout (sem lock de edição)
- **Ícones SVG invisíveis** nos botões de paginação e remoção
- **Ícone apagado** na aba de homologação
- **Largura do diálogo de edição de atributos** ampliada para acomodar campos sem truncamento

### Alterado

- **Carregamento inicial da árvore raster limitado à data mais recente:** reduz o volume de camadas adicionadas ao QGIS; demais datas permanecem disponíveis na hierarquia para carregamento sob demanda
- **Intervalo de polling de status reduzido de 3s para 1s:** transições entre estados intermediários tornam-se mais responsivas nos cards
- **Polling de status inscrito no ciclo contínuo:** cada zonal intermediário é acompanhado até atingir estado terminal, sem depender de consultas pontuais

### Compatibilidade

- Downloads existentes permanecem válidos: o campo `origin` no sidecar é lido com fallback para `mapeamentos` quando ausente
- Zonais baixados em versões anteriores continuam acessíveis em ambas as abas conforme o `origin` gravado no sidecar

## [2.2.0] - 2026-02-22

### Adicionado

- **Editor de atributos tipado:** dialog com secoes colapsaveis, widgets por tipo (combo, data, numerico, multiline), schema de campos com coercao de tipos e agrupamento semantico
- **Dialog de erro intuitivo:** componente visual com resumo + detalhes expandiveis, substituindo mensagens cruas no log
- **Logs HTTP detalhados:** todas as chamadas HTTP agora logam `[HTTP] METHOD url (auth=bool)` com status e tamanho da resposta
- **Tooltips em toda a UI:** todos os botoes e controles possuem tooltips descritivos
- **45 testes de integracao:** cobertura completa da conversao GDAL/OGR (FGB->GPKG download, GPKG export+ZIP upload, roundtrip)
- **Target `make test-integration`** para executar testes de integracao separadamente

### Corrigido

- **Segfault no startup do plugin:** `QNetworkReply` capturado em lambdas era coletado pelo GC do Python antes do signal `finished` disparar, causando acesso a ponteiro C++ invalido. Corrigido em `session_manager`, `auth_controller`, `config_controller` e `client` guardando referencia em `self`
- **Edit tracking nao detectava alteracoes de atributos:** transicao `UPLOADED -> MODIFIED` estava ausente — features ja enviadas ao servidor nao eram re-marcadas ao editar novamente
- **Features novas nao rastreadas:** `addedFeatures()` retornava FIDs temporarios negativos que nao existiam apos commit. Substituido por scan de `_sync_status` NULL
- **Cache stale na tabela de atributos:** apos `dataProvider().changeAttributeValues()`, a layer QGIS mostrava dados antigos. Corrigido com `forceReload()` apos cada escrita via provider
- **Botao Enviar nao habilitava apos editar via dialog:** signal `feature_saved` do dialog nao era propagado ate a aba Camadas. Adicionado signal no `AttributeEditController` conectado ao `edit_tracking_done`
- **Crash no `_close_dialog`:** `close()` emitia signal `finished` sincronamente, setando `_dialog=None` antes de `deleteLater()` na mesma call stack
- **Checkout 409 e pollUrl relativo:** corrigido parsing de URL relativa no polling de upload e mensagem de erro ao tentar checkout ja ativo
- **Endpoints da API zonal:** corrigido paths e parsing de respostas do Feature Server
- **FlatGeobuf corrompido:** adicionada deteccao de FGB invalido com log de metadados para diagnostico
- **Logout no SSO:** plugin agora executa logout no Keycloak ao ser descarregado

### Alterado

- **Tasks migradas para osgeo.ogr:** `DownloadZonalTask` e `UploadZonalTask` agora usam GDAL/OGR puro ao inves de `QgsVectorLayer`/`QgsVectorFileWriter`, evitando segfault por criar objetos QGIS em worker thread
- **Edit tracking refatorado:** usa `dataProvider().changeAttributeValues()` em batch com `QTimer.singleShot(0)` para defer, eliminando nested signal loops e melhorando performance
- **Plugin com lazy init:** imports e inicializacao de controladores diferidos para `_ensure_initialized()`, protegendo contra crash no startup com `try/except`
- **Fluxo V1 removido:** tela de Mapeamentos removida, Catalogo Zonal e agora a tela principal
- **Ortografia e UI:** correcoes de acentuacao e visibilidade em tooltips e labels

### Compatibilidade

- QGIS >= 3.22, GDAL >= 3.4
- GPKGs V1 legados continuam visiveis (somente leitura)
- Total de testes: 187 (142 unitarios + 45 integracao)

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
