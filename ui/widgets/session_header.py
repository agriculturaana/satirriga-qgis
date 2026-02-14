"""Header de sessao — exibe usuario logado ou botao de login."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)


class SessionHeader(QWidget):
    """Widget compacto de sessao para o header do dock."""

    def __init__(self, state, auth_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._auth = auth_controller
        self._countdown_secs = 0

        self._build_ui()
        self._connect_signals()
        self._update_display()

    def _build_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Login button
        self._login_btn = QPushButton("Entrar")
        self._login_btn.setFixedHeight(24)
        self._login_btn.setStyleSheet(
            "QPushButton { background-color: #1976D2; color: white; "
            "border-radius: 4px; padding: 2px 12px; font-size: 11px; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        self._login_btn.clicked.connect(self._on_login_clicked)
        layout.addWidget(self._login_btn)

        # User display (hidden when not authenticated)
        self._user_widget = QWidget()
        user_layout = QHBoxLayout()
        user_layout.setContentsMargins(0, 0, 0, 0)
        user_layout.setSpacing(4)

        self._user_label = QLabel()
        self._user_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        user_layout.addWidget(self._user_label)

        self._countdown_label = QLabel()
        self._countdown_label.setStyleSheet("font-size: 10px; color: #757575;")
        user_layout.addWidget(self._countdown_label)

        self._user_widget.setLayout(user_layout)
        layout.addWidget(self._user_widget)

        self.setLayout(layout)

    def _connect_signals(self):
        self._state.auth_state_changed.connect(self._update_display)
        self._state.user_changed.connect(self._on_user_changed)
        self._state.session_countdown.connect(self._on_countdown)
        self._state.loading_changed.connect(self._on_loading)

    def _update_display(self):
        is_auth = self._state.is_authenticated
        self._login_btn.setVisible(not is_auth)
        self._user_widget.setVisible(is_auth)

    def _on_user_changed(self, user):
        if user:
            display = user.name or user.email or "Usuario"
            self._user_label.setText(display)
        self._update_display()

    def _on_countdown(self, seconds):
        self._countdown_secs = seconds
        mins = seconds // 60
        secs = seconds % 60
        self._countdown_label.setText(f"[{mins}:{secs:02d}]")

        if seconds < 60:
            self._countdown_label.setStyleSheet("font-size: 10px; color: #F44336;")
        elif seconds < 300:
            self._countdown_label.setStyleSheet("font-size: 10px; color: #FF9800;")
        else:
            self._countdown_label.setStyleSheet("font-size: 10px; color: #757575;")

    def _on_loading(self, operation, is_loading):
        if operation == "auth":
            self._login_btn.setEnabled(not is_loading)
            self._login_btn.setText("Aguarde..." if is_loading else "Entrar")

    def _on_login_clicked(self):
        self._auth.start_login()
