"""Aba de serie temporal — marcacao de pontos no mapa e grafico matplotlib."""

import csv
import os
from datetime import datetime, timedelta

from qgis.PyQt.QtCore import Qt, QDate, QSize
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDateEdit, QFileDialog, QSizePolicy, QProgressBar,
)

from ..icon_utils import tinted_icon
from ..theme import SectionHeader

_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "icons",
)


class TimeSeriesTab(QWidget):
    """Aba de consulta de serie temporal com grafico matplotlib."""

    def __init__(self, controller, map_tool, canvas, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._map_tool = map_tool
        self._canvas = canvas
        self._tool_active = False
        self._results = []
        self._figure = None
        self._chart_canvas = None

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Header
        section = SectionHeader("Série Temporal", "consulta")
        layout.addWidget(section)

        # -- Controles de pontos --
        points_row = QHBoxLayout()
        points_row.setSpacing(4)

        self._btn_mark = QPushButton(
            tinted_icon(os.path.join(_ICONS_DIR, "action_map_pin_plus.svg"), "#FFFFFF"),
            "Marcar Pontos",
        )
        self._btn_mark.setIconSize(QSize(14, 14))
        self._btn_mark.setCheckable(True)
        self._btn_mark.setToolTip("Ativar/desativar marcação de pontos no mapa")
        self._btn_mark.setStyleSheet(
            "QPushButton { padding: 4px 10px; border-radius: 4px; font-size: 11px; }"
            "QPushButton:checked { background-color: #1976D2; color: white; }"
        )
        points_row.addWidget(self._btn_mark)

        self._btn_clear = QPushButton(
            QIcon(os.path.join(_ICONS_DIR, "action_map_pin_x.svg")),
            "Limpar",
        )
        self._btn_clear.setIconSize(QSize(14, 14))
        self._btn_clear.setToolTip("Remover todos os pontos marcados")
        self._btn_clear.setFixedWidth(80)
        points_row.addWidget(self._btn_clear)

        points_row.addStretch()

        self._lbl_count = QLabel("0 ponto(s)")
        self._lbl_count.setStyleSheet(
            "font-size: 10px; color: #757575; border: none; background: transparent;"
        )
        points_row.addWidget(self._lbl_count)

        layout.addLayout(points_row)

        # -- Datas --
        dates_row = QHBoxLayout()
        dates_row.setSpacing(4)

        lbl_de = QLabel("De:")
        lbl_de.setFixedWidth(20)
        lbl_de.setStyleSheet("font-size: 11px; border: none; background: transparent;")
        dates_row.addWidget(lbl_de)

        self._date_start = QDateEdit()
        self._date_start.setCalendarPopup(True)
        self._date_start.setDisplayFormat("dd/MM/yyyy")
        self._date_start.setDate(QDate.currentDate().addMonths(-6))
        dates_row.addWidget(self._date_start)

        lbl_ate = QLabel("Até:")
        lbl_ate.setFixedWidth(25)
        lbl_ate.setStyleSheet("font-size: 11px; border: none; background: transparent;")
        dates_row.addWidget(lbl_ate)

        self._date_end = QDateEdit()
        self._date_end.setCalendarPopup(True)
        self._date_end.setDisplayFormat("dd/MM/yyyy")
        self._date_end.setDate(QDate.currentDate())
        dates_row.addWidget(self._date_end)

        layout.addLayout(dates_row)

        # -- Botao consultar --
        self._btn_query = QPushButton(
            tinted_icon(os.path.join(_ICONS_DIR, "action_search.svg"), "#FFFFFF"),
            "Consultar Série Temporal",
        )
        self._btn_query.setIconSize(QSize(14, 14))
        self._btn_query.setEnabled(False)
        self._btn_query.setStyleSheet(
            "QPushButton { padding: 6px 12px; border-radius: 4px; font-size: 12px; "
            "background-color: #1976D2; color: white; font-weight: bold; }"
            "QPushButton:disabled { background-color: #455A64; color: #90A4AE; }"
            "QPushButton:hover:!disabled { background-color: #1565C0; }"
        )
        layout.addWidget(self._btn_query)

        # -- Progress bar --
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminada
        self._progress.setFixedHeight(14)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar { border: 1px solid #455A64; border-radius: 4px; background: #263238; }"
            "QProgressBar::chunk { background: qlineargradient("
            "  x1:0, y1:0, x2:1, y2:0, stop:0 #1976D2, stop:1 #42A5F5); }"
        )
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # -- Status label (sucesso/erro) --
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet(
            "font-size: 10px; color: #757575; border: none; background: transparent;"
        )
        self._lbl_status.setVisible(False)
        layout.addWidget(self._lbl_status)

        # -- Chart placeholder (lazy init) --
        self._chart_container = QWidget()
        self._chart_layout = QVBoxLayout()
        self._chart_layout.setContentsMargins(0, 0, 0, 0)
        self._chart_container.setLayout(self._chart_layout)
        self._chart_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._chart_container, stretch=1)

        # -- Exportação --
        export_row = QHBoxLayout()
        export_row.setSpacing(4)

        self._btn_png = QPushButton(
            QIcon(os.path.join(_ICONS_DIR, "action_image_down.svg")), "PNG",
        )
        self._btn_png.setIconSize(QSize(14, 14))
        self._btn_png.setFixedWidth(70)
        self._btn_png.setEnabled(False)
        self._btn_png.setToolTip("Exportar gráfico como imagem PNG")
        export_row.addWidget(self._btn_png)

        self._btn_csv = QPushButton(
            QIcon(os.path.join(_ICONS_DIR, "action_file_spreadsheet.svg")), "CSV",
        )
        self._btn_csv.setIconSize(QSize(14, 14))
        self._btn_csv.setFixedWidth(70)
        self._btn_csv.setEnabled(False)
        self._btn_csv.setToolTip("Exportar dados como CSV")
        export_row.addWidget(self._btn_csv)

        export_row.addStretch()
        layout.addLayout(export_row)

        self.setLayout(layout)

    def _connect_signals(self):
        self._btn_mark.toggled.connect(self._on_toggle_tool)
        self._btn_clear.clicked.connect(self._on_clear)
        self._btn_query.clicked.connect(self._on_query)
        self._btn_png.clicked.connect(self._on_export_png)
        self._btn_csv.clicked.connect(self._on_export_csv)

        self._map_tool.point_added.connect(self._on_point_added)
        self._map_tool.points_cleared.connect(self._on_points_cleared)

        self._controller.timeseries_data_ready.connect(self._on_data_ready)
        self._controller.timeseries_error.connect(self._on_error)

    # ----------------------------------------------------------------
    # Ações do usuário
    # ----------------------------------------------------------------

    def _on_toggle_tool(self, checked):
        if checked:
            self._canvas.setMapTool(self._map_tool)
            self._tool_active = True
        else:
            self._canvas.unsetMapTool(self._map_tool)
            self._tool_active = False

    def _on_clear(self):
        self._map_tool.clear_points()

    def _on_point_added(self, point):
        count = self._map_tool.point_count()
        self._lbl_count.setText(f"{count} ponto(s)")
        self._btn_query.setEnabled(count > 0)

    def _on_points_cleared(self):
        self._lbl_count.setText("0 ponto(s)")
        self._btn_query.setEnabled(False)

    def _on_query(self):
        points = self._map_tool.get_points()
        if not points:
            return

        start = self._date_start.date().toString("yyyy-MM-dd")
        end = self._date_end.date().toString("yyyy-MM-dd")

        self._progress.setVisible(True)
        self._lbl_status.setVisible(False)
        self._btn_query.setEnabled(False)

        self._controller.fetch_timeseries(points, start, end)

    # ----------------------------------------------------------------
    # Resposta da API
    # ----------------------------------------------------------------

    def _on_data_ready(self, results):
        self._results = results
        self._progress.setVisible(False)
        self._lbl_status.setText(f"{len(results)} série(s) carregada(s)")
        self._lbl_status.setStyleSheet(
            "font-size: 10px; color: #2E7D32; border: none; background: transparent;"
        )
        self._lbl_status.setVisible(True)
        self._btn_query.setEnabled(self._map_tool.point_count() > 0)
        self._btn_png.setEnabled(True)
        self._btn_csv.setEnabled(True)
        self._render_chart(results)

    def _on_error(self, msg):
        self._progress.setVisible(False)
        self._lbl_status.setText(f"Erro: {msg}")
        self._lbl_status.setStyleSheet(
            "font-size: 10px; color: #C62828; border: none; background: transparent;"
        )
        self._lbl_status.setVisible(True)
        self._btn_query.setEnabled(self._map_tool.point_count() > 0)

    # ----------------------------------------------------------------
    # Matplotlib chart (lazy init)
    # ----------------------------------------------------------------

    def _ensure_chart(self):
        """Inicializa matplotlib na primeira renderização."""
        if self._figure is not None:
            return

        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import (
            FigureCanvasQTAgg,
            NavigationToolbar2QT,
        )

        self._figure = Figure(figsize=(5, 3), dpi=100)
        self._figure.set_tight_layout(True)
        self._chart_canvas = FigureCanvasQTAgg(self._figure)
        self._toolbar = NavigationToolbar2QT(self._chart_canvas, self)

        self._chart_layout.addWidget(self._toolbar)
        self._chart_layout.addWidget(self._chart_canvas)

    def _render_chart(self, results):
        """Renderiza gráfico de séries temporais."""
        self._ensure_chart()
        self._figure.clear()

        if not results:
            self._chart_canvas.draw()
            return

        ax_left = self._figure.add_subplot(111)
        ax_right = ax_left.twinx()

        for idx, r in enumerate(results):
            dates = _parse_dates(r.data.dates)
            n = len(dates)
            color = r.color
            label_prefix = f"Ponto {r.id}"

            # EVI original (marcadores — filtra None e alinha com datas)
            evi_orig = _align(r.data.evi_original, n)
            if evi_orig:
                pairs = _filter_pairs(dates, evi_orig, n)
                if pairs:
                    d, v = zip(*pairs)
                    ax_left.scatter(
                        d, v, color=color, marker="o", s=12,
                        alpha=0.4, label=f"{label_prefix} EVI (obs)",
                    )

            # EVI suavizado (linha)
            evi = _align(r.data.evi, n)
            if evi:
                pairs = _filter_pairs(dates, evi, n)
                if pairs:
                    d, v = zip(*pairs)
                    ax_left.plot(
                        d, v, color=color, linewidth=1.5,
                        label=f"{label_prefix} EVI",
                    )

            # NDVI original (marcadores)
            ndvi_orig = _align(r.data.ndvi_original, n)
            if ndvi_orig:
                pairs = _filter_pairs(dates, ndvi_orig, n)
                if pairs:
                    d, v = zip(*pairs)
                    ax_left.scatter(
                        d, v, color=color, marker="^", s=12,
                        alpha=0.4, label=f"{label_prefix} NDVI (obs)",
                    )

            # NDVI suavizado (linha tracejada)
            ndvi = _align(r.data.ndvi, n)
            if ndvi:
                pairs = _filter_pairs(dates, ndvi, n)
                if pairs:
                    d, v = zip(*pairs)
                    ax_left.plot(
                        d, v, color=color, linewidth=1.5,
                        linestyle="--", label=f"{label_prefix} NDVI",
                    )

            # Precipitação (barras — somente primeiro ponto)
            if idx == 0:
                precip = _align(r.data.precipitation, n)
                if precip:
                    pairs = [
                        (dates[i], precip[i])
                        for i in range(n)
                        if dates[i] is not None and precip[i] is not None
                    ]
                    if pairs:
                        d, v = zip(*pairs)
                        ax_right.bar(
                            d, v, color="#B0BEC5", alpha=0.4,
                            width=timedelta(days=6),
                            label="Precipitação (mm)",
                        )

        ax_left.set_ylim(0, 1.2)
        ax_left.set_ylabel("EVI / NDVI", fontsize=9)
        ax_right.set_ylabel("Precipitação (mm)", fontsize=9)

        # Legenda combinada — posição fora do gráfico para não obstruir
        lines_l, labels_l = ax_left.get_legend_handles_labels()
        lines_r, labels_r = ax_right.get_legend_handles_labels()
        if lines_l or lines_r:
            ax_left.legend(
                lines_l + lines_r, labels_l + labels_r,
                loc="upper center", bbox_to_anchor=(0.5, -0.18),
                ncol=2, fontsize=7, framealpha=0.9,
                borderaxespad=0,
            )

        ax_left.tick_params(axis="x", rotation=45, labelsize=7)
        ax_left.tick_params(axis="y", labelsize=8)
        ax_right.tick_params(axis="y", labelsize=8)

        self._figure.subplots_adjust(bottom=0.30)
        self._chart_canvas.draw()

    # ----------------------------------------------------------------
    # Exportação
    # ----------------------------------------------------------------

    def _on_export_png(self):
        if not self._figure:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar gráfico como PNG", "", "Imagens PNG (*.png)",
        )
        if path:
            self._figure.savefig(path, dpi=150, bbox_inches="tight")

    def _on_export_csv(self):
        if not self._results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar dados como CSV", "", "CSV (*.csv)",
        )
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Cabeçalho
            header = ["data"]
            for r in self._results:
                prefix = r.label or f"Ponto {r.id}"
                header.extend([
                    f"{prefix}_evi", f"{prefix}_evi_original",
                    f"{prefix}_ndvi", f"{prefix}_ndvi_original",
                    f"{prefix}_precipitacao",
                ])
            writer.writerow(header)

            # Dados (baseado no primeiro resultado para datas)
            if self._results:
                dates = self._results[0].data.dates
                for i, date in enumerate(dates):
                    row = [date]
                    for r in self._results:
                        row.append(_safe_get(r.data.evi, i))
                        row.append(_safe_get(r.data.evi_original, i))
                        row.append(_safe_get(r.data.ndvi, i))
                        row.append(_safe_get(r.data.ndvi_original, i))
                        row.append(_safe_get(r.data.precipitation, i))
                    writer.writerow(row)

    # ----------------------------------------------------------------
    # Controle do map tool
    # ----------------------------------------------------------------

    def deactivate_tool(self):
        """Desativa o map tool (chamado ao sair da aba)."""
        if self._tool_active:
            self._btn_mark.setChecked(False)

    def set_data_referencia(self, data_ref):
        """Auto-preenche datas a partir de data_referencia do mapeamento.

        Aceita ISO datetime (2025-09-30T00:00:00Z), ISO date (2025-09-30)
        ou formato brasileiro (30/09/2025).
        """
        if not data_ref:
            return
        try:
            # Remove timezone suffix e pega apenas a parte de data
            date_str = data_ref.split("T")[0].strip()

            # Tenta ISO (YYYY-MM-DD)
            if "-" in date_str and len(date_str) >= 10:
                parts = date_str.split("-")
                qdate = QDate(int(parts[0]), int(parts[1]), int(parts[2]))
            # Tenta BR (DD/MM/YYYY)
            elif "/" in date_str:
                parts = date_str.split("/")
                qdate = QDate(int(parts[2]), int(parts[1]), int(parts[0]))
            else:
                return

            if qdate.isValid():
                self._date_start.setDate(qdate.addMonths(-6))
                self._date_end.setDate(qdate.addMonths(6))
        except (ValueError, TypeError, IndexError):
            pass


def _filter_pairs(dates, values, n):
    """Retorna pares (date, value) onde ambos sao validos (nao-None)."""
    return [
        (dates[i], values[i])
        for i in range(n)
        if dates[i] is not None and values[i] is not None
    ]


def _align(data_list, n):
    """Alinha lista de dados ao tamanho n de datas.

    Trunca se maior, preenche com None se menor.
    Retorna None se a lista estiver vazia.
    """
    if not data_list:
        return None
    if len(data_list) >= n:
        return data_list[:n]
    return data_list + [None] * (n - len(data_list))


def _parse_dates(date_strings):
    """Converte lista de strings ISO para datetime para matplotlib."""
    result = []
    for s in date_strings:
        try:
            result.append(datetime.fromisoformat(s.replace("Z", "+00:00")))
        except (ValueError, TypeError):
            result.append(None)
    return result


def _safe_get(lst, idx):
    """Acesso seguro a lista, retorna '' se fora de limites ou None."""
    if lst and idx < len(lst) and lst[idx] is not None:
        return lst[idx]
    return ""
