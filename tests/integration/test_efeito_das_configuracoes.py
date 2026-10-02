"""Efeito das configurações do plugin sobre a paginação, a consulta periódica e o registro de mensagens, com QGIS real."""

import importlib
import pathlib
import sys
import types
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PACKAGE = "satirriga_configuracoes"
package = types.ModuleType(_PACKAGE)
package.__path__ = [str(_ROOT)]
sys.modules[_PACKAGE] = package
_PREVIOUS_QGIS = {name: module for name, module in sys.modules.items() if name == "qgis" or name.startswith("qgis.")}
for name in _PREVIOUS_QGIS:
    sys.modules.pop(name)
try:
    from qgis.core import Qgis, QgsApplication
    settings = importlib.import_module(f"{_PACKAGE}.infra.config.settings")
    store = importlib.import_module(f"{_PACKAGE}.app.state.store")
    controller_module = importlib.import_module(f"{_PACKAGE}.app.controllers.mapeamento_controller")
    client_module = importlib.import_module(f"{_PACKAGE}.infra.http.client")
    catalogo_module = importlib.import_module(f"{_PACKAGE}.ui.widgets.mapeamentos_tab")
    homologacao_module = importlib.import_module(f"{_PACKAGE}.ui.widgets.homologacao_tab")
    historico_module = importlib.import_module(f"{_PACKAGE}.ui.widgets.upload_history_widget")
    _REAL_QGIS = {name: module for name, module in sys.modules.items() if name == "qgis" or name.startswith("qgis.")}
finally:
    for name in list(sys.modules):
        if name == "qgis" or name.startswith("qgis."):
            sys.modules.pop(name)
    sys.modules.update(_PREVIOUS_QGIS)


@pytest.fixture(autouse=True)
def qgis_environment(monkeypatch):
    for name, module in _REAL_QGIS.items():
        monkeypatch.setitem(sys.modules, name, module)
    app = QgsApplication.instance() or QgsApplication([], False)
    app.initQgis()
    yield app


class FakeConfig:
    """Configurações em memória: os testes não podem gravar no perfil do QGIS do usuário."""

    def __init__(self, **values):
        self.values = {**settings.DEFAULTS, "api_base_url": "http://sat/api", **values}

    def get(self, key):
        return self.values[key]


def controller_with(**values):
    state = store.AppState()
    state.is_authenticated = True
    http = MagicMock()
    controller = controller_module.MapeamentoController(state, http, FakeConfig(**values), token_provider=lambda: "token")
    return controller, http, state


def requested_size(http):
    return parse_qs(urlparse(http.get.call_args.args[0]).query)["size"]


def test_catalogo_pede_ao_servidor_a_quantidade_de_itens_configurada():
    controller, http, state = controller_with(page_size=7)
    catalogo_module.MapeamentosTab(state, controller)._request_page()
    assert requested_size(http) == ["7"]


def test_homologacao_pede_ao_servidor_a_quantidade_de_itens_configurada():
    controller, http, state = controller_with(page_size=7)
    homologacao_module.HomologacaoTab(state, controller)._load_data()
    assert requested_size(http) == ["7"]


def test_historico_pede_ao_servidor_a_quantidade_de_itens_configurada():
    controller, http, state = controller_with(page_size=7)
    historico_module.UploadHistoryWidget(state, controller)._request_page()
    assert requested_size(http) == ["7"]


def test_consulta_periodica_segue_o_intervalo_configurado_e_a_sua_alteracao():
    controller, _, state = controller_with(polling_interval_ms=2500)
    try:
        controller.start_polling_zonal(42)
        assert controller._poll_timer.interval() == 2500
        controller._config.values["polling_interval_ms"] = 4000
        state.config_changed.emit({"polling_interval_ms"})
        assert controller._poll_timer.interval() == 4000
    finally:
        controller.cleanup_polling()


def test_intervalo_padrao_mantem_a_consulta_de_situacao_a_cada_segundo():
    controller, _, _ = controller_with()
    try:
        controller.start_polling_zonal(42)
        assert controller._poll_timer.interval() == 1000
    finally:
        controller.cleanup_polling()


@pytest.fixture
def received_messages(monkeypatch):
    message_log = importlib.import_module(f"{_PACKAGE}.infra.message_log")
    received = []

    def configure(level):
        monkeypatch.setattr(message_log, "ConfigRepository", lambda: FakeConfig(log_level=level))
        return received

    def receive(message, tag, level):
        if tag == settings.PLUGIN_NAME:
            received.append((message, level))

    QgsApplication.messageLog().messageReceived.connect(receive)
    yield configure
    QgsApplication.messageLog().messageReceived.disconnect(receive)


def test_registro_omite_as_mensagens_abaixo_do_nivel_configurado(received_messages):
    message_log = importlib.import_module(f"{_PACKAGE}.infra.message_log")
    received = received_messages("WARNING")
    message_log.log_message("consulta de rotina", settings.PLUGIN_NAME, Qgis.Info)
    message_log.log_message("falha recuperável", settings.PLUGIN_NAME, Qgis.Warning)
    message_log.log_message("falha grave", settings.PLUGIN_NAME, Qgis.Critical)
    assert received == [("falha recuperável", Qgis.Warning), ("falha grave", Qgis.Critical)]


def test_requisicoes_http_deixam_de_ser_registradas_no_nivel_de_erro(received_messages):
    received = received_messages("ERROR")
    client = client_module.HttpClient()
    client.get("http://127.0.0.1:9/api/zonal/catalogo")
    for reply in list(client._pending.values()):
        reply.abort()
    assert received == []


def test_nenhum_modulo_registra_mensagens_sem_passar_pelo_nivel_configurado():
    # O domínio não depende da infraestrutura e, por isso, mantém o registro direto no QGIS.
    excluded = {_ROOT / "infra" / "message_log.py"}
    bypassing = [
        str(path.relative_to(_ROOT))
        for path in _ROOT.rglob("*.py")
        if path not in excluded and "tests" not in path.parts and "domain" not in path.parts
        and "QgsMessageLog.logMessage(" in path.read_text(encoding="utf-8")
    ]
    assert bypassing == []
