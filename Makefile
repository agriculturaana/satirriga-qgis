#/***************************************************************************
# SatIrriga QGIS Plugin v2
#
# Makefile para build, deploy e testes do plugin.
# ***************************************************************************/

PLUGINNAME = satirriga_qgis

# Deploy dir (QGIS 3.22+)
DEPLOY_DIR = $(HOME)/.local/share/QGIS/QGIS3/profiles/default/python/plugins/$(PLUGINNAME)

# Locales (space separated ISO codes; empty = disabled)
LOCALES =

# Python source directories (recursive)
SRC_DIRS = domain infra app ui
SRC_PY = $(shell find $(SRC_DIRS) -name '*.py' 2>/dev/null)

# Root-level Python files
ROOT_PY = __init__.py plugin.py

# Extra files to deploy
EXTRAS = metadata.txt icon.png logo.png CHANGELOG.md

# Directories to deploy in full
EXTRA_DIRS = assets i18n

# Compiled Qt resources
COMPILED_RESOURCE_FILES = resources.py

# -----------------------------------------------------------------------
# Targets
# -----------------------------------------------------------------------

# Tamanho maximo do ZIP para OSGEO (20 MB)
MAX_ZIP_SIZE_KB = 20480

# Diretorio temporario para montagem do pacote
BUILD_DIR = build/$(PLUGINNAME)

# Arquivos obrigatorios no pacote OSGEO
REQUIRED_FILES = metadata.txt __init__.py plugin.py resources.py icon.png LICENSE

# Campos obrigatorios no metadata.txt (OSGEO)
REQUIRED_META = name qgisMinimumVersion description about version author email repository tracker

.PHONY: default compile deploy test test-unit clean package publish validate help

default: help

help:
	@echo "Targets disponiveis:"
	@echo "  compile      — Compila resources.qrc -> resources.py"
	@echo "  deploy       — Copia plugin para diretorio QGIS local"
	@echo "  test         — Executa todos os testes (pytest)"
	@echo "  test-unit    — Executa somente testes unitarios"
	@echo "  clean        — Remove arquivos gerados"
	@echo "  package      — Cria ZIP para distribuicao (requer VERSION=vX.Y.Z)"
	@echo "  publish      — Valida e empacota para publicar no plugins.qgis.org"
	@echo "  validate     — Valida metadata e estrutura sem empacotar"
	@echo "  pylint       — Executa pylint"

compile: $(COMPILED_RESOURCE_FILES)

%.py: %.qrc
	pyrcc5 -o $@ $<

deploy: compile
	@echo "Deploying $(PLUGINNAME) to $(DEPLOY_DIR) ..."
	@mkdir -p $(DEPLOY_DIR)
	@# Root files
	@cp -v $(ROOT_PY) $(DEPLOY_DIR)/
	@cp -v $(COMPILED_RESOURCE_FILES) $(DEPLOY_DIR)/
	@cp -v $(EXTRAS) $(DEPLOY_DIR)/ 2>/dev/null || true
	@# Source directories (preserving structure)
	@for dir in $(SRC_DIRS); do \
		find $$dir -name '*.py' | while read f; do \
			mkdir -p $(DEPLOY_DIR)/$$(dirname $$f); \
			cp -v $$f $(DEPLOY_DIR)/$$f; \
		done; \
	done
	@# Extra dirs
	@for dir in $(EXTRA_DIRS); do \
		if [ -d $$dir ]; then cp -rv $$dir $(DEPLOY_DIR)/; fi; \
	done
	@echo "Deploy concluido."

test: compile
	@echo "Executando testes..."
	python3 -m pytest tests/ -v --tb=short

test-unit: compile
	@echo "Executando testes unitarios..."
	python3 -m pytest tests/unit/ -v --tb=short

clean:
	@echo "Limpando arquivos gerados..."
	rm -f $(COMPILED_RESOURCE_FILES)
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage

derase:
	@echo "Removendo plugin do QGIS..."
	rm -rf $(DEPLOY_DIR)

package: compile
	@echo "Criando pacote $(PLUGINNAME).zip ..."
	rm -f $(PLUGINNAME).zip
	git archive --prefix=$(PLUGINNAME)/ -o $(PLUGINNAME).zip $(VERSION)
	@echo "Pacote criado: $(PLUGINNAME).zip"

# -----------------------------------------------------------------------
# Validacao e publicacao (OSGEO)
# -----------------------------------------------------------------------

validate:
	@echo "=== Validando plugin para plugins.qgis.org ==="
	@echo ""
	@ERRORS=0; \
	echo "[1/5] Verificando arquivos obrigatorios..."; \
	for f in $(REQUIRED_FILES); do \
		if [ ! -f "$$f" ]; then \
			echo "  ERRO: arquivo obrigatorio ausente: $$f"; \
			ERRORS=$$((ERRORS + 1)); \
		else \
			echo "  OK: $$f"; \
		fi; \
	done; \
	echo ""; \
	echo "[2/5] Verificando campos do metadata.txt..."; \
	for field in $(REQUIRED_META); do \
		VALUE=$$(grep -m1 "^$$field=" metadata.txt 2>/dev/null | cut -d= -f2-); \
		if [ -z "$$VALUE" ]; then \
			echo "  ERRO: campo obrigatorio ausente: $$field"; \
			ERRORS=$$((ERRORS + 1)); \
		else \
			echo "  OK: $$field = $$VALUE"; \
		fi; \
	done; \
	echo ""; \
	echo "[3/5] Verificando URLs no metadata.txt..."; \
	for field in repository tracker homepage; do \
		URL=$$(grep -m1 "^$$field=" metadata.txt 2>/dev/null | cut -d= -f2-); \
		if echo "$$URL" | grep -qiE "(TODO|example\.com|localhost|http://bugs|http://repo|http://homepage)"; then \
			echo "  ERRO: URL placeholder em $$field: $$URL"; \
			ERRORS=$$((ERRORS + 1)); \
		elif [ -n "$$URL" ]; then \
			echo "  OK: $$field = $$URL"; \
		fi; \
	done; \
	echo ""; \
	echo "[4/5] Verificando version (dotted notation)..."; \
	VER=$$(grep -m1 "^version=" metadata.txt | cut -d= -f2-); \
	if echo "$$VER" | grep -qE "^[0-9]+\.[0-9]+(\.[0-9]+)?$$"; then \
		echo "  OK: version = $$VER"; \
	else \
		echo "  ERRO: version nao esta em dotted notation: $$VER"; \
		ERRORS=$$((ERRORS + 1)); \
	fi; \
	echo ""; \
	echo "[5/5] Verificando arquivos proibidos..."; \
	FORBIDDEN=0; \
	for pattern in .git .gitignore CLAUDE.md __pycache__ "*.pyc" pb_tool.cfg; do \
		FOUND=$$(find . -maxdepth 3 -name "$$pattern" 2>/dev/null | head -3); \
		if [ -n "$$FOUND" ] && [ "$$pattern" != ".git" ] && [ "$$pattern" != ".gitignore" ]; then \
			echo "  AVISO: $$pattern encontrado (sera excluido do ZIP)"; \
		fi; \
	done; \
	echo "  OK: arquivos proibidos serao excluidos no empacotamento"; \
	echo ""; \
	if [ $$ERRORS -gt 0 ]; then \
		echo "FALHOU: $$ERRORS erro(s) encontrado(s). Corrija antes de publicar."; \
		exit 1; \
	else \
		echo "APROVADO: plugin pronto para empacotar (make publish)."; \
	fi

publish: compile validate
	@echo ""
	@echo "=== Empacotando $(PLUGINNAME) para plugins.qgis.org ==="
	@echo ""
	@# Limpa build anterior
	rm -rf build/$(PLUGINNAME) $(PLUGINNAME).zip
	mkdir -p $(BUILD_DIR)
	@# Root files
	@cp $(ROOT_PY) $(BUILD_DIR)/
	@cp $(COMPILED_RESOURCE_FILES) $(BUILD_DIR)/
	@cp metadata.txt LICENSE icon.png $(BUILD_DIR)/
	@cp logo.png CHANGELOG.md README.txt README.html $(BUILD_DIR)/ 2>/dev/null || true
	@# Source directories (somente .py)
	@for dir in $(SRC_DIRS); do \
		find $$dir -name '*.py' | while read f; do \
			mkdir -p $(BUILD_DIR)/$$(dirname $$f); \
			cp $$f $(BUILD_DIR)/$$f; \
		done; \
	done
	@# Extra dirs (assets, i18n)
	@for dir in $(EXTRA_DIRS); do \
		if [ -d $$dir ]; then \
			cp -r $$dir $(BUILD_DIR)/; \
		fi; \
	done
	@# Remove artefatos proibidos do pacote
	@find $(BUILD_DIR) -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	@find $(BUILD_DIR) -name '*.pyc' -delete 2>/dev/null || true
	@find $(BUILD_DIR) -name '.git*' -delete 2>/dev/null || true
	@rm -f $(BUILD_DIR)/CLAUDE.md $(BUILD_DIR)/pb_tool.cfg 2>/dev/null || true
	@# Cria ZIP com estrutura correta (pasta raiz = nome do plugin)
	@cd build && zip -r ../$(PLUGINNAME).zip $(PLUGINNAME)/ -x '*.pyc' '*__pycache__*'
	@rm -rf build
	@# Valida tamanho
	@SIZE_KB=$$(du -k $(PLUGINNAME).zip | cut -f1); \
	SIZE_MB=$$(echo "scale=1; $$SIZE_KB / 1024" | bc); \
	echo ""; \
	if [ $$SIZE_KB -gt $(MAX_ZIP_SIZE_KB) ]; then \
		echo "ERRO: ZIP excede 20 MB ($$SIZE_MB MB). Reduza o pacote."; \
		rm -f $(PLUGINNAME).zip; \
		exit 1; \
	else \
		echo "Tamanho: $$SIZE_MB MB (limite: 20 MB)"; \
	fi
	@# Resumo do conteudo
	@echo ""
	@echo "Conteudo do pacote:"
	@unzip -l $(PLUGINNAME).zip | tail -1
	@echo ""
	@echo "Pacote criado: $(PLUGINNAME).zip"
	@echo "Envie em: https://plugins.qgis.org/plugins/add/"

pylint:
	@pylint --rcfile=pylintrc $(ROOT_PY) $(SRC_DIRS) || true

transup:
	@chmod +x scripts/update-strings.sh
	@scripts/update-strings.sh $(LOCALES)

transcompile:
	@chmod +x scripts/compile-strings.sh
	@scripts/compile-strings.sh $(LRELEASE) $(LOCALES)
