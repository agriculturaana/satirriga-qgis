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
            self.DONE: "Concluido",
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
