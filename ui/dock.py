import os

from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QDockWidget, QVBoxLayout, QHBoxLayout, QWidget,
    QStackedWidget, QLabel,
)

from ..infra.config.settings import (
    PLUGIN_VERSION, ENVIRONMENT_COLORS, ENVIRONMENT_LABELS,
)
from .widgets.activity_bar import ActivityBar
from .theme import DOCK_STYLESHEET


class SatIrrigaDock(QDockWidget):
    """Dock principal do plugin com Activity Bar + QStackedWidget."""

    closed = pyqtSignal()

    # Indices das paginas
    PAGE_MAPEAMENTOS = 0
    PAGE_CAMADAS = 1
    PAGE_CONFIG = 2
    PAGE_LOGS = 3

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
        container.setStyleSheet(DOCK_STYLESHEET)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header_widget = QWidget()
        header_widget.setStyleSheet("border-bottom: 1px solid palette(mid);")
        self._header = self._build_header()
        header_widget.setLayout(self._header)
        header_widget.setFixedHeight(44)
        main_layout.addWidget(header_widget)

        # Content: ActivityBar + QStackedWidget
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # Activity Bar
        self._activity_bar = ActivityBar()
        self._setup_nav_buttons()
        content.addWidget(self._activity_bar)

        # Pages
        self._pages = QStackedWidget()
        self._pages.setStyleSheet("")

        # Placeholders (serao substituidos via set_page_widget)
        for label_text in ("Mapeamentos (requer login)", "Camadas locais",
                           "Configuracoes", "Logs"):
            placeholder = QLabel(label_text)
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("font-size: 12px;")
            self._pages.addWidget(placeholder)

        content.addWidget(self._pages)

        content_widget = QWidget()
        content_widget.setLayout(content)
        main_layout.addWidget(content_widget)

        container.setLayout(main_layout)
        self.setWidget(container)

    def _build_header(self):
        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 4)
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
                pixmap.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        logo_label.setFixedSize(28, 28)
        header.addWidget(logo_label)

        # Title
        title = QLabel(f"SatIrriga v{PLUGIN_VERSION}")
        title.setStyleSheet("font-size: 13px; font-weight: bold; border: none;")
        header.addWidget(title)

        # Environment chip
        env = self._config.get("environment")
        env_label = ENVIRONMENT_LABELS.get(env, env.upper()[:3])
        env_color = ENVIRONMENT_COLORS.get(env, "#9E9E9E")
        self._env_chip = QLabel(env_label)
        self._env_chip.setStyleSheet(
            f"background-color: {env_color}; color: white; "
            f"padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; border: none;"
        )
        self._env_chip.setFixedHeight(18)
        header.addWidget(self._env_chip)

        header.addStretch()

        # User area (sera substituido pelo SessionHeader via plugin.py)
        self._user_label = QLabel("Nao autenticado")
        self._user_label.setStyleSheet("font-size: 11px; border: none;")
        header.addWidget(self._user_label)

        return header

    def _setup_nav_buttons(self):
        """Cria botoes de navegacao na Activity Bar."""
        self._activity_bar.add_button("nav_mapeamentos", "Mapeamentos", self.PAGE_MAPEAMENTOS)
        self._activity_bar.add_button("nav_camadas", "Camadas", self.PAGE_CAMADAS)
        self._activity_bar.add_stretch()
        self._activity_bar.add_button("nav_config", "Configuracoes", self.PAGE_CONFIG)
        self._activity_bar.add_button("nav_logs", "Logs", self.PAGE_LOGS)

    def _connect_signals(self):
        self._activity_bar.page_changed.connect(self._pages.setCurrentIndex)
        self._state.auth_state_changed.connect(self._on_auth_changed)
        self._state.user_changed.connect(self._on_user_changed)

    def _on_auth_changed(self, is_authenticated):
        if isinstance(self._user_label, QLabel) and not is_authenticated:
            self._user_label.setText("Nao autenticado")

    def _on_user_changed(self, user):
        if not isinstance(self._user_label, QLabel):
            return
        if user:
            display = getattr(user, "name", None) or getattr(user, "email", "Usuario")
            self._user_label.setText(display)
        else:
            self._user_label.setText("Nao autenticado")

    def set_page_widget(self, page_index, widget):
        """Substitui placeholder de uma pagina por widget real."""
        old = self._pages.widget(page_index)
        self._pages.removeWidget(old)
        if old:
            old.deleteLater()
        self._pages.insertWidget(page_index, widget)

    @property
    def activity_bar(self):
        return self._activity_bar

    @property
    def pages(self):
        return self._pages

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
