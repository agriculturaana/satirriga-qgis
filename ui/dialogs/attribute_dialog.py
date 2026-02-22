"""Dialog de edicao de atributos de uma feature zonal.

Abre ao selecionar 1 feature no mapa. Exibe atributos agrupados em
secoes colapsaveis com widgets adequados (combos, datas, numeros).
Salva via dataProvider().changeAttributeValues() — sem startEditing.
"""

from datetime import datetime, timezone

from qgis.PyQt.QtCore import Qt, QVariant, pyqtSignal, QDate
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QLineEdit, QComboBox,
    QDoubleSpinBox, QDateEdit, QTextEdit, QShortcut, QFrame,
)
from qgis.PyQt.QtGui import QKeySequence

from ...domain.models.enums import SyncStatusEnum
from ...domain.services.attribute_schema import (
    FieldWidgetType,
    build_field_groups,
    get_field_spec,
    is_internal_field,
    collect_unique_values,
    FieldGroup,
)
from ..widgets.collapsible_section import CollapsibleSection


# Cores de badge por sync status (espelhado de camadas_tab._SYNC_COLORS)
_SYNC_COLORS = {
    "DOWNLOADED": "#2196F3",
    "MODIFIED": "#FF9800",
    "UPLOADED": "#4CAF50",
    "NEW": "#9C27B0",
}

_DIALOG_STYLESHEET = """
QDoubleSpinBox {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
QDoubleSpinBox:focus {
    border: 1px solid #1976D2;
}
QDateEdit {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
QDateEdit:focus {
    border: 1px solid #1976D2;
}
QTextEdit {
    border: 1px solid palette(mid);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}
QTextEdit:focus {
    border: 1px solid #1976D2;
}
QScrollArea {
    border: none;
}
"""


class AttributeEditDialog(QDialog):
    """Dialog para edicao de atributos de uma feature."""

    feature_saved = pyqtSignal(int)  # fid apos salvar

    def __init__(self, layer, feature, parent=None):
        super().__init__(parent)
        self._layer = layer
        self._feature = feature
        self._fid = feature.id()
        self._widgets = {}  # field_name -> widget

        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self):
        self.setWindowTitle("Editar Atributos")
        self.setMinimumWidth(480)
        self.setMinimumHeight(500)
        self.setStyleSheet(_DIALOG_STYLESHEET)

        root = QVBoxLayout()
        root.setSpacing(8)

        # --- Header ---
        root.addLayout(self._build_header())

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # --- Body: scroll com secoes ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        self._body_layout = QVBoxLayout()
        self._body_layout.setContentsMargins(4, 4, 4, 4)
        self._body_layout.setSpacing(6)

        self._populate_sections()

        self._body_layout.addStretch()
        container.setLayout(self._body_layout)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # --- Footer ---
        root.addLayout(self._build_footer())

        self.setLayout(root)

    def _build_header(self):
        header = QHBoxLayout()

        # Sync status badge
        sync_status = self._feature.attribute("_sync_status") or ""
        color = _SYNC_COLORS.get(sync_status, "#9E9E9E")
        badge = QLabel(sync_status or "—")
        badge.setStyleSheet(
            f"background-color: {color}; color: white; "
            "font-size: 10px; font-weight: bold; "
            "padding: 2px 8px; border-radius: 3px;"
        )
        badge.setFixedHeight(20)
        header.addWidget(badge)

        # Feature ID
        fid_label = QLabel(f"Feature #{self._fid}")
        fid_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        header.addWidget(fid_label)

        # Classe (se existir)
        classe_idx = self._layer.fields().indexOf("classe")
        if classe_idx >= 0:
            classe = self._feature.attribute(classe_idx) or ""
            if classe:
                classe_lbl = QLabel(f"— {classe}")
                classe_lbl.setStyleSheet("font-size: 12px; color: #616161;")
                header.addWidget(classe_lbl)

        header.addStretch()
        return header

    def _populate_sections(self):
        """Cria secoes colapsaveis com os campos agrupados."""
        groups = build_field_groups()

        # Coleta nomes dos campos presentes no layer
        layer_field_names = {f.name() for f in self._layer.fields()}

        # Campos ja mapeados a um grupo
        mapped_fields = set()

        for group in groups:
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight)
            has_fields = False

            for fspec in group.fields:
                if fspec.name not in layer_field_names:
                    continue
                widget = self._create_widget(fspec)
                if widget is None:
                    continue
                self._load_value(fspec, widget)
                form.addRow(f"{fspec.label}:", widget)
                self._widgets[fspec.name] = widget
                mapped_fields.add(fspec.name)
                has_fields = True

            if has_fields:
                section = CollapsibleSection(
                    title=group.label,
                    icon=group.icon,
                    expanded=True,
                )
                section.set_content_layout(form)
                self._body_layout.addWidget(section)

        # Campos nao mapeados (novos do servidor) -> secao "Outros"
        unmapped = []
        for fname in layer_field_names:
            if fname in mapped_fields or is_internal_field(fname) or fname == "fid":
                continue
            unmapped.append(fname)

        if unmapped:
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight)
            for fname in sorted(unmapped):
                fspec = get_field_spec(fname)
                widget = self._create_widget(fspec)
                if widget is None:
                    continue
                self._load_value(fspec, widget)
                form.addRow(f"{fspec.label}:", widget)
                self._widgets[fname] = widget

            section = CollapsibleSection(
                title="Outros",
                icon="📦",
                expanded=False,
            )
            section.set_content_layout(form)
            self._body_layout.addWidget(section)

    def _create_widget(self, fspec):
        """Cria widget adequado ao tipo do campo."""
        wtype = fspec.widget_type

        if wtype == FieldWidgetType.HIDDEN:
            return None

        if wtype == FieldWidgetType.READ_ONLY:
            lbl = QLabel()
            lbl.setStyleSheet(
                "font-size: 12px; color: #616161; "
                "padding: 4px 8px;"
            )
            return lbl

        if wtype == FieldWidgetType.NUMERIC:
            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(-999999999.0, 999999999.0)
            spin.setSpecialValueText("")
            if fspec.tooltip:
                spin.setToolTip(fspec.tooltip)
            return spin

        if wtype == FieldWidgetType.COMBO:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.NoInsert)

            # Valores do schema
            values = list(fspec.combo_values)

            # Mescla com valores reais do layer
            layer_values = collect_unique_values(self._layer, fspec.name)
            for v in layer_values:
                if v not in values:
                    values.append(v)

            combo.addItem("")  # opcao vazia
            for v in values:
                combo.addItem(v)

            if fspec.tooltip:
                combo.setToolTip(fspec.tooltip)
            return combo

        if wtype == FieldWidgetType.DATE:
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("dd/MM/yyyy")
            date_edit.setSpecialValueText("")
            if fspec.tooltip:
                date_edit.setToolTip(fspec.tooltip)
            return date_edit

        if wtype == FieldWidgetType.MULTILINE:
            text = QTextEdit()
            text.setMaximumHeight(80)
            if fspec.tooltip:
                text.setToolTip(fspec.tooltip)
            return text

        # Default: TEXT
        line = QLineEdit()
        if fspec.tooltip:
            line.setToolTip(fspec.tooltip)
        return line

    def _load_value(self, fspec, widget):
        """Carrega o valor atual da feature no widget."""
        idx = self._layer.fields().indexOf(fspec.name)
        if idx < 0:
            return

        val = self._feature.attribute(idx)
        val_str = "" if val is None else str(val).strip()

        wtype = fspec.widget_type

        if wtype == FieldWidgetType.READ_ONLY:
            widget.setText(val_str)

        elif wtype == FieldWidgetType.NUMERIC:
            try:
                widget.setValue(float(val) if val is not None else 0.0)
            except (TypeError, ValueError):
                widget.setValue(0.0)

        elif wtype == FieldWidgetType.COMBO:
            idx_combo = widget.findText(val_str)
            if idx_combo >= 0:
                widget.setCurrentIndex(idx_combo)
            else:
                widget.setCurrentText(val_str)

        elif wtype == FieldWidgetType.DATE:
            if val_str:
                # Tenta parsear ISO date ou dd/MM/yyyy
                for fmt in ("yyyy-MM-dd", "dd/MM/yyyy"):
                    qdate = QDate.fromString(val_str[:10], fmt)
                    if qdate.isValid():
                        widget.setDate(qdate)
                        return
            widget.setSpecialValueText("")
            widget.setDate(widget.minimumDate())

        elif wtype == FieldWidgetType.MULTILINE:
            widget.setPlainText(val_str)

        else:
            widget.setText(val_str)

    def _read_value(self, fspec, widget):
        """Le o valor do widget para gravar no provider."""
        wtype = fspec.widget_type

        if wtype == FieldWidgetType.READ_ONLY:
            return None  # nao salva

        if wtype == FieldWidgetType.NUMERIC:
            return widget.value()

        if wtype == FieldWidgetType.COMBO:
            text = widget.currentText().strip()
            return text if text else None

        if wtype == FieldWidgetType.DATE:
            if widget.date() == widget.minimumDate():
                return None
            return widget.date().toString("yyyy-MM-dd")

        if wtype == FieldWidgetType.MULTILINE:
            text = widget.toPlainText().strip()
            return text if text else None

        # TEXT / fallback
        text = widget.text().strip()
        return text if text else None

    def _coerce_to_field_type(self, val, field):
        """Converte valor para o tipo nativo do campo GPKG (Int/Real/String)."""
        if val is None:
            return None
        ftype = field.type()
        if ftype in (QVariant.Int, QVariant.LongLong):
            try:
                return int(float(val))
            except (TypeError, ValueError):
                return None
        if ftype == QVariant.Double:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        if ftype == QVariant.String:
            return str(val)
        return val

    def _build_footer(self):
        footer = QHBoxLayout()
        footer.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setToolTip("Fechar sem salvar (Esc)")
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #9E9E9E; color: white; "
            "border: none; padding: 6px 16px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #757575; }"
        )
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        btn_save = QPushButton("Salvar")
        btn_save.setToolTip("Salvar alterações (Ctrl+S)")
        btn_save.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border: none; padding: 6px 16px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #388E3C; }"
        )
        btn_save.clicked.connect(self._save)
        footer.addWidget(btn_save)

        return footer

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)

    def _save(self):
        """Salva atributos via dataProvider — sem startEditing/commitChanges."""
        fields = self._layer.fields()
        attr_changes = {}  # {field_idx: new_value}

        for fname, widget in self._widgets.items():
            fspec = get_field_spec(fname)
            val = self._read_value(fspec, widget)
            if val is None and fspec.widget_type == FieldWidgetType.READ_ONLY:
                continue
            fidx = fields.indexOf(fname)
            if fidx < 0:
                continue
            attr_changes[fidx] = self._coerce_to_field_type(val, fields.at(fidx))

        # Atualiza _sync_status -> MODIFIED (se era DOWNLOADED)
        sync_idx = fields.indexOf("_sync_status")
        ts_idx = fields.indexOf("_sync_timestamp")

        if sync_idx >= 0:
            current = self._feature.attribute(sync_idx)
            if current in (SyncStatusEnum.DOWNLOADED.value,
                           SyncStatusEnum.MODIFIED.value,
                           SyncStatusEnum.UPLOADED.value):
                attr_changes[sync_idx] = SyncStatusEnum.MODIFIED.value

        if ts_idx >= 0:
            attr_changes[ts_idx] = datetime.now(timezone.utc).isoformat()

        if attr_changes:
            self._layer.dataProvider().changeAttributeValues(
                {self._fid: attr_changes}
            )
            # Invalida cache para refletir mudancas na tabela de atributos
            self._layer.dataProvider().forceReload()
            self._layer.triggerRepaint()
            self.feature_saved.emit(self._fid)

        self.accept()
