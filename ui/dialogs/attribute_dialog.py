"""Dialog de edicao de atributos de uma feature zonal.

Abre ao selecionar 1 feature no mapa. Exibe atributos agrupados em
secoes colapsaveis com widgets adequados (combos, datas, numeros).
Salva via dataProvider().changeAttributeValues() — sem startEditing.
"""

import os
from datetime import datetime, timezone

from qgis.PyQt.QtCore import Qt, QVariant, QSize, pyqtSignal, QDate
from qgis.PyQt.QtGui import QIcon, QKeySequence
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QLineEdit, QComboBox,
    QDoubleSpinBox, QDateEdit, QTextEdit, QShortcut, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)
from ..icon_utils import tinted_icon

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
    "DELETED": "#F44336",
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

    def __init__(self, layer, feature, parent=None, overlay_data=None):
        super().__init__(parent)
        self._layer = layer
        self._feature = feature
        self._fid = feature.id()
        self._widgets = {}  # field_name -> widget
        self._overlay = overlay_data  # dict from /api/zonal/:id/overlay-data

        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self):
        self.setWindowTitle("Editar Atributos")
        self.setMinimumWidth(720)
        self.setMinimumHeight(500)
        self.resize(780, 600)
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

        # --- Secao Overlay (dados de overlay.overlay via API) ---
        self._populate_overlay_section()

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

    def inject_overlay(self, overlay_data):
        """Injeta dados de overlay tardiamente (quando chegam apos o dialog abrir)."""
        self._overlay = overlay_data
        self._populate_overlay_section(late_inject=True)

    def _populate_overlay_section(self, late_inject=False):
        """Cria secao read-only com dados de overlay (municipio, bacia, empreendimentos).

        Args:
            late_inject: se True, insere antes do stretch (ultima posicao util).
        """
        from qgis.core import QgsMessageLog, Qgis
        _TAG = "SatIrriga"

        if not self._overlay:
            QgsMessageLog.logMessage(
                f"[Overlay/Dialog] overlay vazio ou None para feature #{self._fid}",
                _TAG, Qgis.Info,
            )
            return

        # Resolve overlay para esta feature pelo _original_fid (= ZonalGeometria.id)
        original_fid_idx = self._layer.fields().indexOf("_original_fid")
        if original_fid_idx < 0:
            QgsMessageLog.logMessage(
                f"[Overlay/Dialog] campo _original_fid nao encontrado no layer",
                _TAG, Qgis.Warning,
            )
            return
        original_fid = self._feature.attribute(original_fid_idx)
        if original_fid is None:
            QgsMessageLog.logMessage(
                f"[Overlay/Dialog] _original_fid e NULL para feature #{self._fid}",
                _TAG, Qgis.Warning,
            )
            return

        overlay_keys = list(self._overlay.keys())[:5]
        entry = self._overlay.get(str(original_fid)) or self._overlay.get(original_fid)
        if not entry:
            QgsMessageLog.logMessage(
                f"[Overlay/Dialog] chave {original_fid!r} (tipo {type(original_fid).__name__}) "
                f"nao encontrada no overlay. Chaves disponiveis: {overlay_keys}",
                _TAG, Qgis.Warning,
            )
            return

        layout = QVBoxLayout()

        # --- Localizacao ---
        loc_form = QFormLayout()
        loc_form.setLabelAlignment(Qt.AlignRight)
        loc_fields = [
            ("Municipio", entry.get("munnm")),
            ("Cod. Municipio", entry.get("muncd")),
            ("UF", entry.get("ufdsg")),
            ("Bacia", entry.get("baf_nm")),
            ("Cod. Bacia", entry.get("baf_cd")),
        ]
        for label, value in loc_fields:
            if value is not None:
                lbl = QLabel(str(value))
                lbl.setStyleSheet("font-size: 12px; color: #424242; padding: 2px 8px;")
                loc_form.addRow(f"{label}:", lbl)

        if loc_form.rowCount() > 0:
            layout.addLayout(loc_form)

        # --- Empreendimentos (tabela) ---
        empre = entry.get("empre")
        if isinstance(empre, list) and len(empre) > 0:
            emp_label = QLabel(f"Empreendimentos ({len(empre)})")
            emp_label.setStyleSheet(
                "font-size: 11px; font-weight: bold; color: #616161; "
                "padding: 4px 0 2px 0;"
            )
            layout.addWidget(emp_label)

            headers = ["Codigo", "Nome", "Usuario", "CPF/CNPJ", "NARH"]
            table = QTableWidget(len(empre), len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            table.setStyleSheet(
                "QTableWidget { font-size: 11px; border: 1px solid palette(mid); }"
                "QHeaderView::section { font-size: 11px; font-weight: bold; "
                "padding: 4px; background: palette(midlight); }"
            )

            for row, emp in enumerate(empre):
                cpf_cnpj = emp.get("usunucnpj") or emp.get("usunucpf") or ""
                values = [
                    emp.get("empcd", ""),
                    emp.get("empnm", ""),
                    emp.get("usunm", ""),
                    str(cpf_cnpj),
                    emp.get("intnucnarh") or "",
                ]
                for col, val in enumerate(values):
                    table.setItem(row, col, QTableWidgetItem(str(val)))

            row_h = 26
            table.setFixedHeight(min(row_h * len(empre) + 30, 200))
            layout.addWidget(table)

        if loc_form.rowCount() > 0 or (isinstance(empre, list) and len(empre) > 0):
            section = CollapsibleSection(
                title="Overlay",
                icon="",
                expanded=True,
            )
            section.set_content_layout(layout)

            if late_inject:
                # Insere antes do stretch (ultimo item do layout)
                stretch_idx = self._body_layout.count() - 1
                self._body_layout.insertWidget(
                    max(stretch_idx, 0), section,
                )
            else:
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

        btn_cancel = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_ban.svg"), "#FFFFFF"), "Cancelar")
        btn_cancel.setIconSize(QSize(14, 14))
        btn_cancel.setToolTip("Fechar sem salvar (Esc)")
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #9E9E9E; color: white; "
            "border: none; padding: 6px 16px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #757575; }"
        )
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)

        btn_save = QPushButton(tinted_icon(os.path.join(_ICONS_DIR, "action_save.svg"), "#FFFFFF"), "Salvar")
        btn_save.setIconSize(QSize(14, 14))
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
