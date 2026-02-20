### SatIrriga QGIS — Plugin v2

Consulte, baixe, edite e envie mapeamentos de irrigacao direto no QGIS.

#### Requisitos

- QGIS 3.22 ou superior
- Acesso ao servidor SatIrriga (credenciais SSO)

#### Instalacao

1. Copie a pasta do plugin para o diretorio de plugins do QGIS:
   `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/satirriga_qgis/`
   Ou use: `make deploy`
2. Abra o QGIS e ative o plugin em **Plugins > Gerenciar e Instalar Plugins**

#### Desenvolvimento

- `make compile` — Compila resources.qrc -> resources.py
- `make deploy` — Copia plugin para diretorio QGIS local
- `make test` — Executa todos os testes (pytest)
- `make test-unit` — Executa somente testes unitarios
- `make clean` — Remove arquivos gerados
- `make derase` — Remove plugin do diretorio QGIS
- `make package VERSION=vX.Y.Z` — Cria ZIP para distribuicao via git archive
- `make validate` — Valida metadata e estrutura para plugins.qgis.org
- `make publish` — Valida e empacota ZIP para publicar no plugins.qgis.org
- `make pylint` — Executa pylint no codigo fonte

#### Uso

1. Clique no icone **SatIrriga** na toolbar
2. Faca login na aba **Sessao**
3. Navegue pelos mapeamentos, baixe classificacoes e edite geometrias
4. Envie as alteracoes pela aba **Camadas**

Repositorio: [github.com/agriculturaana/satirriga-qgis](https://github.com/agriculturaana/satirriga-qgis)