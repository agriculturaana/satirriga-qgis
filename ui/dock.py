import os

from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QDockWidget, QVBoxLayout, QHBoxLayout, QWidget,
    QTabWidget, QLabel,
)

from ..infra.config.settings import (
    PLUGIN_VERSION, ENVIRONMENT_COLORS, ENVIRONMENT_LABELS,
)


class SatIrrigaDock(QDockWidget):
    """Dock principal do plugin com abas."""

    closed = pyqtSignal()

    def __init__(self, state, config_repo, parent=None):
        super().__init__(parent)
        self._state = state
        self._config = config_repo
        self.setWindowTitle(f"SatIrriga v{PLUGIN_VERSION}")
        self.setObjectName("SatIrrigaDock")

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        container = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        self._header = self._build_header()
        layout.addLayout(self._header)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._mapeamentos_placeholder = QLabel("Mapeamentos (requer login)")
        self._mapeamentos_placeholder.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(self._mapeamentos_placeholder, "Mapeamentos")

        self._camadas_placeholder = QLabel("Camadas locais")
        self._camadas_placeholder.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(self._camadas_placeholder, "Camadas")

        self._config_placeholder = QLabel("Configuracoes")
        self._config_placeholder.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(self._config_placeholder, "Config")

        self._sessao_placeholder = QLabel("Sessao (requer login)")
        self._sessao_placeholder.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(self._sessao_placeholder, "Sessao")

        self._logs_placeholder = QLabel("Logs")
        self._logs_placeholder.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(self._logs_placeholder, "Logs")

        layout.addWidget(self._tabs)

        container.setLayout(layout)
        self.setWidget(container)

    def _build_header(self):
        header = QHBoxLayout()
        header.setSpacing(8)

        # Logo
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        logo_path = os.path.join(plugin_dir, "assets", "logo.png")
        if not os.path.exists(logo_path):
            logo_path = os.path.join(plugin_dir, "logo.png")

        logo_label = QLabel()
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(
                pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        logo_label.setFixedSize(32, 32)
        header.addWidget(logo_label)

        # Title
        title = QLabel(f"SatIrriga v{PLUGIN_VERSION}")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header.addWidget(title)

        # Environment chip
        env = self._config.get("environment")
        env_label = ENVIRONMENT_LABELS.get(env, env.upper()[:3])
        env_color = ENVIRONMENT_COLORS.get(env, "#9E9E9E")
        self._env_chip = QLabel(env_label)
        self._env_chip.setStyleSheet(
            f"background-color: {env_color}; color: white; "
            f"padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;"
        )
        self._env_chip.setFixedHeight(20)
        header.addWidget(self._env_chip)

        header.addStretch()

        # User area (will be replaced by SessionHeader widget in Phase 2)
        self._user_label = QLabel("Nao autenticado")
        self._user_label.setStyleSheet("font-size: 11px; color: #757575;")
        header.addWidget(self._user_label)

        return header

    def _connect_signals(self):
        self._state.auth_state_changed.connect(self._on_auth_changed)
        self._state.user_changed.connect(self._on_user_changed)

    def _on_auth_changed(self, is_authenticated):
        if not is_authenticated:
            self._user_label.setText("Nao autenticado")

    def _on_user_changed(self, user):
        if user:
            display = getattr(user, "name", None) or getattr(user, "email", "Usuario")
            self._user_label.setText(display)
        else:
            self._user_label.setText("Nao autenticado")

    def replace_tab(self, index, widget, title=None):
        """Substitui o placeholder de uma aba por um widget real."""
        old = self._tabs.widget(index)
        current_title = title or self._tabs.tabText(index)
        self._tabs.removeTab(index)
        self._tabs.insertTab(index, widget, current_title)
        if old:
            old.deleteLater()

    @property
    def tabs(self):
        return self._tabs

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
