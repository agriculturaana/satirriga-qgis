"""Session Popup — card overlay com detalhes da sessao e logout."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QFrame, QVBoxLayout, QFormLayout, QLabel, QPushButton,
    QHBoxLayout,
)


class SessionPopup(QFrame):
    """Card flutuante com detalhes da sessao do usuario."""

    def __init__(self, state, auth_controller, parent=None):
        super().__init__(parent)
        self._state = state
        self._auth = auth_controller

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setFixedWidth(300)

        self._setup_style()
        self._build_ui()
        self._connect_signals()

    def _setup_style(self):
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "SessionPopup {"
            "  background-color: palette(window);"
            "  border: 1px solid palette(mid);"
            "}"
        )

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Titulo
        title = QLabel("Sessao")
        title.setStyleSheet(
            "font-size: 14px; font-weight: bold; border: none;"
        )
        layout.addWidget(title)

        # Separador
        layout.addWidget(self._make_separator())

        # Detalhes do usuario
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(6)

        self._name_label = QLabel("-")
        self._name_label.setStyleSheet("font-weight: bold; border: none;")
        form.addRow(self._make_form_label("Nome:"), self._name_label)

        self._email_label = QLabel("-")
        self._email_label.setStyleSheet("border: none;")
        form.addRow(self._make_form_label("Email:"), self._email_label)

        self._username_label = QLabel("-")
        self._username_label.setStyleSheet("border: none;")
        form.addRow(self._make_form_label("Username:"), self._username_label)

        self._roles_label = QLabel("-")
        self._roles_label.setWordWrap(True)
        self._roles_label.setStyleSheet("border: none;")
        form.addRow(self._make_form_label("Roles:"), self._roles_label)

        layout.addLayout(form)

        # Countdown
        countdown_layout = QHBoxLayout()
        countdown_title = QLabel("Expira em:")
        countdown_title.setStyleSheet("font-size: 11px; border: none;")
        countdown_layout.addWidget(countdown_title)

        self._countdown_label = QLabel("-")
        self._countdown_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #4CAF50; border: none;"
        )
        self._countdown_label.setAlignment(Qt.AlignCenter)
        countdown_layout.addWidget(self._countdown_label)
        countdown_layout.addStretch()
        layout.addLayout(countdown_layout)

        # Separador
        layout.addWidget(self._make_separator())

        # Botao logout
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._logout_btn = QPushButton("Logout")
        self._logout_btn.setFixedWidth(120)
        self._logout_btn.setToolTip("Encerrar sessao e revogar tokens")
        self._logout_btn.setCursor(Qt.PointingHandCursor)
        self._logout_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "border-radius: 4px; padding: 6px 16px; border: none; }"
            "QPushButton:hover { background-color: #D32F2F; }"
        )
        self._logout_btn.clicked.connect(self._on_logout)
        btn_layout.addWidget(self._logout_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _make_separator(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; background-color: palette(mid); max-height: 1px;")
        return sep

    def _make_form_label(self, text):
        label = QLabel(text)
        label.setStyleSheet("font-size: 11px; border: none;")
        return label

    def _connect_signals(self):
        self._state.user_changed.connect(self._on_user_changed)
        self._state.session_countdown.connect(self._on_countdown)

    def _on_user_changed(self, user):
        if user:
            self._name_label.setText(user.name or "-")
            self._email_label.setText(user.email or "-")
            self._username_label.setText(user.preferred_username or "-")
            self._roles_label.setText(", ".join(user.roles) if user.roles else "-")

    def _on_countdown(self, seconds):
        mins = seconds // 60
        secs = seconds % 60
        self._countdown_label.setText(f"{mins}:{secs:02d}")

        if seconds < 60:
            self._countdown_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #F44336; border: none;"
            )
        elif seconds < 300:
            self._countdown_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #FF9800; border: none;"
            )
        else:
            self._countdown_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #4CAF50; border: none;"
            )

    def _on_logout(self):
        self.hide()
        self._auth.logout()

    def show_below(self, reference_widget):
        """Posiciona o popup abaixo do widget de referencia e exibe."""
        user = self._state.user
        if user:
            self._on_user_changed(user)

        pos = reference_widget.mapToGlobal(reference_widget.rect().bottomRight())
        pos.setX(pos.x() - self.width())
        pos.setY(pos.y() + 4)
        self.move(pos)
        self.show()
