"""Schema de campos para edicao de atributos de features zonais.

Define tipos de widget, especificacoes de campo e agrupamento logico
para renderizar formularios intuitivos no dialog de edicao.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set


class FieldWidgetType(Enum):
    """Tipo de widget a renderizar para cada campo."""
    READ_ONLY = "read_only"
    TEXT = "text"
    NUMERIC = "numeric"
    COMBO = "combo"
    DATE = "date"
    MULTILINE = "multiline"
    HIDDEN = "hidden"


@dataclass
class FieldSpec:
    """Especificacao de um campo para renderizacao no dialog."""
    name: str
    label: str
    widget_type: FieldWidgetType
    group: str
    tooltip: str = ""
    read_only: bool = False
    combo_values: List[str] = field(default_factory=list)


@dataclass
class FieldGroup:
    """Grupo logico de campos para secao colapsavel."""
    name: str
    label: str
    icon: str
    fields: List[FieldSpec]


# Campos internos de sync — nunca exibidos ao usuario
INTERNAL_FIELDS: Set[str] = {
    "_original_fid",
    "_sync_status",
    "_sync_timestamp",
    "_zonal_id",
    "_edit_token",
}


def _build_schema() -> dict:
    """Constroi dicionario name -> FieldSpec com todos os campos conhecidos."""
    specs = {}

    def _add(name, label, wtype, group, tooltip="", read_only=False, combo_values=None):
        specs[name] = FieldSpec(
            name=name,
            label=label,
            widget_type=wtype,
            group=group,
            tooltip=tooltip,
            read_only=read_only,
            combo_values=combo_values or [],
        )

    # --- Identificacao ---
    _add("id", "ID", FieldWidgetType.READ_ONLY, "identificacao",
         "Identificador unico da feature", read_only=True)
    _add("classe", "Classe", FieldWidgetType.COMBO, "identificacao",
         "Classe de uso do solo",
         combo_values=["Irrigado", "Nao Irrigado", "Corpo Dagua", "Vegetacao", "Solo Exposto"])
    _add("status_validacao", "Status Validação", FieldWidgetType.COMBO, "identificacao",
         "Status de validação da feature",
         combo_values=["Pendente", "Validado", "Rejeitado", "Revisao"])

    # --- Medidas ---
    _add("area_ha", "Área (ha)", FieldWidgetType.NUMERIC, "medidas",
         "Área em hectares")
    _add("perimetro_m", "Perímetro (m)", FieldWidgetType.NUMERIC, "medidas",
         "Perímetro em metros")
    _add("confiabilidade", "Confiabilidade", FieldWidgetType.NUMERIC, "medidas",
         "Índice de confiabilidade (0-100)")

    # --- Agricultura ---
    _add("irrigacao_tipo", "Tipo Irrigação", FieldWidgetType.COMBO, "agricultura",
         "Tipo de irrigação identificada",
         combo_values=["Pivô Central", "Aspersão", "Gotejamento", "Sulco",
                       "Inundação", "Microaspersão", "Não Identificado"])
    _add("cultura_principal", "Cultura Principal", FieldWidgetType.COMBO, "agricultura",
         "Cultura principal identificada",
         combo_values=["Soja", "Milho", "Algodão", "Café", "Cana-de-Açúcar",
                       "Arroz", "Feijão", "Trigo", "Hortaliças", "Fruticultura"])
    _add("cultura_secundaria", "Cultura Secundária", FieldWidgetType.COMBO, "agricultura",
         "Cultura secundária, se houver")
    _add("sistema_irrigacao", "Sistema Irrigação", FieldWidgetType.COMBO, "agricultura",
         "Sistema de irrigação em uso",
         combo_values=["Pivô Central", "Linear", "Carretel", "Gotejamento",
                       "Microaspersão", "Sulco", "Inundação"])

    # --- Localizacao ---
    _add("municipio", "Município", FieldWidgetType.TEXT, "localizacao",
         "Município onde se localiza a feature")
    _add("estado", "Estado", FieldWidgetType.TEXT, "localizacao",
         "Unidade federativa")
    _add("bioma", "Bioma", FieldWidgetType.TEXT, "localizacao",
         "Bioma predominante")
    _add("bacia_hidrografica", "Bacia Hidrográfica", FieldWidgetType.TEXT, "localizacao",
         "Bacia hidrográfica principal")
    _add("sub_bacia", "Sub-bacia", FieldWidgetType.TEXT, "localizacao",
         "Sub-bacia hidrográfica")

    # --- Outorga ---
    _add("ponto_captacao", "Ponto Captação", FieldWidgetType.TEXT, "outorga",
         "Ponto de captação de água")
    _add("outorga_numero", "Nº Outorga", FieldWidgetType.TEXT, "outorga",
         "Número da outorga de uso de água")
    _add("outorga_validade", "Validade Outorga", FieldWidgetType.DATE, "outorga",
         "Data de validade da outorga")
    _add("responsavel", "Responsável", FieldWidgetType.TEXT, "outorga",
         "Responsável pelo uso da água")
    _add("contato", "Contato", FieldWidgetType.TEXT, "outorga",
         "Contato do responsável")

    # --- Metadados ---
    _add("data_referencia", "Data Referência", FieldWidgetType.DATE, "metadados",
         "Data de referência do mapeamento")
    _add("fonte", "Fonte", FieldWidgetType.TEXT, "metadados",
         "Fonte dos dados")
    _add("observacao", "Observação", FieldWidgetType.MULTILINE, "metadados",
         "Observações gerais sobre a feature")
    _add("validado_por", "Validado por", FieldWidgetType.TEXT, "metadados",
         "Usuário que validou a feature")
    _add("data_validacao", "Data Validação", FieldWidgetType.DATE, "metadados",
         "Data em que a feature foi validada")

    return specs


# Schema global (lazy singleton)
_FIELD_SCHEMA: Optional[dict] = None


def _get_schema() -> dict:
    global _FIELD_SCHEMA
    if _FIELD_SCHEMA is None:
        _FIELD_SCHEMA = _build_schema()
    return _FIELD_SCHEMA


# Definicao dos grupos na ordem de exibicao
_GROUP_DEFS = [
    ("identificacao", "Identificação", "🏷️"),
    ("medidas", "Medidas", "📐"),
    ("agricultura", "Agricultura", "🌾"),
    ("localizacao", "Localização", "📍"),
    ("outorga", "Outorga", "💧"),
    ("metadados", "Metadados", "📋"),
]


def build_field_groups() -> List[FieldGroup]:
    """Retorna lista ordenada de grupos com seus campos."""
    schema = _get_schema()

    # Agrupa specs por grupo
    by_group = {}
    for spec in schema.values():
        by_group.setdefault(spec.group, []).append(spec)

    groups = []
    for gname, glabel, gicon in _GROUP_DEFS:
        fields = by_group.get(gname, [])
        if fields:
            groups.append(FieldGroup(name=gname, label=glabel, icon=gicon, fields=fields))

    return groups


def get_field_spec(name: str) -> FieldSpec:
    """Retorna spec de um campo pelo nome, com fallback para TEXT generico."""
    schema = _get_schema()
    if name in schema:
        return schema[name]
    # Fallback: campo desconhecido vira TEXT editavel em grupo "outros"
    label = name.replace("_", " ").title()
    return FieldSpec(
        name=name,
        label=label,
        widget_type=FieldWidgetType.TEXT,
        group="outros",
        tooltip=f"Campo: {name}",
    )


def is_internal_field(name: str) -> bool:
    """True se o campo e interno de sync (comeca com _ ou esta em INTERNAL_FIELDS)."""
    return name.startswith("_") or name in INTERNAL_FIELDS


def collect_unique_values(layer, field_name: str, limit: int = 50) -> List[str]:
    """Coleta valores unicos de um campo no layer para popular combos.

    Args:
        layer: QgsVectorLayer com os dados.
        field_name: Nome do campo.
        limit: Maximo de valores distintos a retornar.

    Returns:
        Lista de strings com valores unicos, ordenada alfabeticamente.
    """
    idx = layer.fields().indexOf(field_name)
    if idx < 0:
        return []

    values = set()
    for feat in layer.getFeatures():
        val = feat.attribute(idx)
        if val is not None and str(val).strip():
            values.add(str(val).strip())
        if len(values) >= limit:
            break

    return sorted(values)
