#/***************************************************************************
# SatIrriga QGIS Plugin v2
#
# Makefile para build, deploy e testes do plugin.
# ***************************************************************************/

PLUGINNAME = satirriga_cliente

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
EXTRAS = metadata.txt icon.png logo.png

# Directories to deploy in full
EXTRA_DIRS = assets i18n

# Compiled Qt resources
COMPILED_RESOURCE_FILES = resources.py

# -----------------------------------------------------------------------
# Targets
# -----------------------------------------------------------------------

.PHONY: default compile deploy test test-unit clean package help

default: help

help:
	@echo "Targets disponiveis:"
	@echo "  compile      — Compila resources.qrc -> resources.py"
	@echo "  deploy       — Copia plugin para diretorio QGIS local"
	@echo "  test         — Executa todos os testes (pytest)"
	@echo "  test-unit    — Executa somente testes unitarios"
	@echo "  clean        — Remove arquivos gerados"
	@echo "  package      — Cria ZIP para distribuicao (requer VERSION=vX.Y.Z)"
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
	python -m pytest tests/ -v --tb=short

test-unit: compile
	@echo "Executando testes unitarios..."
	python -m pytest tests/unit/ -v --tb=short

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

pylint:
	@pylint --rcfile=pylintrc $(ROOT_PY) $(SRC_DIRS) || true

transup:
	@chmod +x scripts/update-strings.sh
	@scripts/update-strings.sh $(LOCALES)

transcompile:
	@chmod +x scripts/compile-strings.sh
	@scripts/compile-strings.sh $(LRELEASE) $(LOCALES)
