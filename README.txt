SatIrriga QGIS — Plugin v2

Consulte, baixe, edite e envie mapeamentos de irrigacao direto no QGIS.

Requisitos:
  * QGIS 3.22 ou superior
  * Acesso ao servidor SatIrriga (credenciais SSO)

Instalacao:
  1. Copie a pasta do plugin para o diretorio de plugins do QGIS:
     ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/satirriga_cliente/
     Ou use: make deploy

  2. Abra o QGIS e ative o plugin em Plugins > Gerenciar e Instalar Plugins

Desenvolvimento:
  * make deploy    — Deploya no QGIS local
  * make test      — Roda todos os testes
  * make test-unit — Roda somente testes unitarios
  * make compile   — Compila resources.qrc
  * make clean     — Limpa arquivos gerados

Uso:
  1. Clique no icone SatIrriga na toolbar
  2. Faca login na aba Sessao
  3. Navegue pelos mapeamentos, baixe classificacoes e edite geometrias
  4. Envie as alteracoes pela aba Camadas

Repositorio: https://github.com/agriculturaana/satirriga-qgis
