from enum import Enum


class JobStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"

    @property
    def color(self):
        return {
            self.PENDING: "#9E9E9E",
            self.PROCESSING: "#FF9800",
            self.DONE: "#4CAF50",
            self.FAILED: "#F44336",
        }.get(self, "#9E9E9E")

    @property
    def label(self):
        return {
            self.PENDING: "Pendente",
            self.PROCESSING: "Processando",
            self.DONE: "Concluído",
            self.FAILED: "Falhou",
        }.get(self, self.value)


class MetodoMapeamentoEnum(str, Enum):
    MANUAL = "MANUAL"
    RANDOM_FOREST = "RANDOM_FOREST"
    SVM = "SVM"
    DEEP_LEARNING = "DEEP_LEARNING"

    @property
    def label(self):
        return {
            self.MANUAL: "Manual",
            self.RANDOM_FOREST: "Random Forest",
            self.SVM: "SVM",
            self.DEEP_LEARNING: "Deep Learning",
        }.get(self, self.value)


class SyncStatusEnum(str, Enum):
    DOWNLOADED = "DOWNLOADED"
    MODIFIED = "MODIFIED"
    UPLOADED = "UPLOADED"
    NEW = "NEW"
    DELETED = "DELETED"


class ZonalStatusEnum(str, Enum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"
    CONSOLIDATING = "CONSOLIDATING"
    CONSOLIDATED = "CONSOLIDATED"
    CONSOLIDATION_FAILED = "CONSOLIDATION_FAILED"
    OVERLAID = "OVERLAID"
    OVERLAY_FAILED = "OVERLAY_FAILED"
    INVALIDATED = "INVALIDATED"
    AGUARDANDO = "AGUARDANDO"
    HOMOLOGADO = "HOMOLOGADO"
    REPROVADO = "REPROVADO"
    CANCELADO = "CANCELADO"

    @property
    def label(self):
        return {
            self.CREATED: "Criado",
            self.PROCESSING: "Processando",
            self.DONE: "Concluído",
            self.FAILED: "Falhou",
            self.CONSOLIDATING: "Consolidando",
            self.CONSOLIDATED: "Consolidado",
            self.CONSOLIDATION_FAILED: "Falha na consolidação",
            self.OVERLAID: "Overlay concluído",
            self.OVERLAY_FAILED: "Falha no overlay",
            self.INVALIDATED: "Invalidado",
            self.AGUARDANDO: "Aguardando",
            self.HOMOLOGADO: "Homologado",
            self.REPROVADO: "Reprovado",
            self.CANCELADO: "Cancelado",
        }.get(self, self.value)

    @property
    def color(self):
        return {
            self.CREATED: "#9E9E9E",
            self.PROCESSING: "#FF9800",
            self.DONE: "#4CAF50",
            self.FAILED: "#F44336",
            self.CONSOLIDATING: "#2196F3",
            self.CONSOLIDATED: "#1B5E20",
            self.CONSOLIDATION_FAILED: "#B71C1C",
            self.OVERLAID: "#42A5F5",
            self.OVERLAY_FAILED: "#B71C1C",
            self.INVALIDATED: "#795548",
            self.AGUARDANDO: "#FFC107",
            self.HOMOLOGADO: "#2E7D32",
            self.REPROVADO: "#C62828",
            self.CANCELADO: "#616161",
        }.get(self, "#9E9E9E")


class UploadBatchStatusEnum(str, Enum):
    RECEIVED = "RECEIVED"
    STAGING = "STAGING"
    VALIDATING_STRUCTURE = "VALIDATING_STRUCTURE"
    VALIDATING_SCHEMA = "VALIDATING_SCHEMA"
    VALIDATING_TOPOLOGY = "VALIDATING_TOPOLOGY"
    DIFFING = "DIFFING"
    CONFLICT_CHECKING = "CONFLICT_CHECKING"
    RECONCILING = "RECONCILING"
    PROMOTING = "PROMOTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def label(self):
        return {
            self.RECEIVED: "Recebido",
            self.STAGING: "Preparando",
            self.VALIDATING_STRUCTURE: "Validando estrutura",
            self.VALIDATING_SCHEMA: "Validando schema",
            self.VALIDATING_TOPOLOGY: "Validando topologia",
            self.DIFFING: "Calculando diferenças",
            self.CONFLICT_CHECKING: "Verificando conflitos",
            self.RECONCILING: "Reconciliando",
            self.PROMOTING: "Promovendo",
            self.COMPLETED: "Concluído",
            self.FAILED: "Falhou",
            self.CANCELLED: "Cancelado",
        }.get(self, self.value)

    @property
    def is_terminal(self):
        return self in (self.COMPLETED, self.FAILED, self.CANCELLED)


class ConflictResolutionEnum(str, Enum):
    TAKE_MINE = "TAKE_MINE"
    TAKE_THEIRS = "TAKE_THEIRS"
    MERGE = "MERGE"


class DownloadOrigin(str, Enum):
    MAPEAMENTOS = "mapeamentos"
    HOMOLOGACAO = "homologacao"

    @property
    def label(self):
        return {
            self.MAPEAMENTOS: "Mapeamentos",
            self.HOMOLOGACAO: "Homologação",
        }.get(self, self.value)

    @classmethod
    def coerce(cls, value):
        """Converte string para enum, com fallback para MAPEAMENTOS."""
        if isinstance(value, cls):
            return value
        if not value:
            return cls.MAPEAMENTOS
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.MAPEAMENTOS
