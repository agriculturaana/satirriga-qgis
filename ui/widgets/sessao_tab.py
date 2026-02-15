"""DEPRECATED: Logica migrada para session_popup.py e session_header.py.

Aba de sessao — detalhes do usuario logado + logout.
Mantido apenas para referencia. Nao e mais importado pelo plugin.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QPushButton,
    QHBoxLayout,
)


class SessaoTab(QWidget):
    """Aba com detalhes da sessao e botao de logout."""

    def __init__(self, state, auth_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._auth = auth_controller

        self._build_ui()
        self._connect_signals()
        self._update_display()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)

        # Not authenticated message
        self._not_auth_label = QLabel("Nao autenticado.\nClique em 'Entrar' no header.")
        self._not_auth_label.setAlignment(Qt.AlignCenter)
        self._not_auth_label.setStyleSheet("color: #757575; font-size: 12px;")
        layout.addWidget(self._not_auth_label)

        # Session details
        self._details_widget = QWidget()
        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self._name_label = QLabel("-")
        self._name_label.setStyleSheet("font-weight: bold;")
        form.addRow("Nome:", self._name_label)

        self._email_label = QLabel("-")
        form.addRow("Email:", self._email_label)

        self._username_label = QLabel("-")
        form.addRow("Username:", self._username_label)

        self._roles_label = QLabel("-")
        self._roles_label.setWordWrap(True)
        form.addRow("Roles:", self._roles_label)

        self._countdown_label = QLabel("-")
        self._countdown_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        form.addRow("Expira em:", self._countdown_label)

        details_layout.addLayout(form)
        details_layout.addStretch()

        # Logout button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._logout_btn = QPushButton("Logout")
        self._logout_btn.setFixedWidth(120)
        self._logout_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #D32F2F; }"
        )
        self._logout_btn.clicked.connect(self._on_logout)
        btn_layout.addWidget(self._logout_btn)
        btn_layout.addStretch()
        details_layout.addLayout(btn_layout)

        self._details_widget.setLayout(details_layout)
        layout.addWidget(self._details_widget)

        self.setLayout(layout)

    def _connect_signals(self):
        self._state.auth_state_changed.connect(self._update_display)
        self._state.user_changed.connect(self._on_user_changed)
        self._state.session_countdown.connect(self._on_countdown)

    def _update_display(self):
        is_auth = self._state.is_authenticated
        self._not_auth_label.setVisible(not is_auth)
        self._details_widget.setVisible(is_auth)

    def _on_user_changed(self, user):
        if user:
            self._name_label.setText(user.name or "-")
            self._email_label.setText(user.email or "-")
            self._username_label.setText(user.preferred_username or "-")
            self._roles_label.setText(", ".join(user.roles) if user.roles else "-")
        self._update_display()

    def _on_countdown(self, seconds):
        mins = seconds // 60
        secs = seconds % 60
        self._countdown_label.setText(f"{mins}:{secs:02d}")

        if seconds < 60:
            self._countdown_label.setStyleSheet(
                "font-size: 18px; font-weight: bold; color: #F44336;"
            )
        elif seconds < 300:
            self._countdown_label.setStyleSheet(
                "font-size: 18px; font-weight: bold; color: #FF9800;"
            )
        else:
            self._countdown_label.setStyleSheet(
                "font-size: 18px; font-weight: bold; color: #4CAF50;"
            )

    def _on_logout(self):
        self._auth.logout()
