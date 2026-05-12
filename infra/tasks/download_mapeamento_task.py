"""Task para download de mapeamento homologado (GPKG consolidado, read-only).

Sem checkout e sem campos de sincronizacao V2 — o GPKG e entregue pronto
pelo servidor via GET /api/mapeamento/homologados/gpkg e nao participa
do fluxo de edicao zonal.
"""

import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

import requests

from .base_task import SatIrrigaTask
from ...domain.models.enums import DownloadOrigin
from ...domain.services.gpkg_service import read_sidecar, write_sidecar


_GPKG_MAGIC = b"SQLite format 3\x00"
_ZIP_MAGIC = b"PK\x03\x04"


def _is_valid_gpkg_file(path):
    """Sniff dos primeiros bytes: True somente se for SQLite/GPKG cru."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
        return head.startswith(_GPKG_MAGIC)
    except OSError:
        return False


def _extract_gpkg_from_zip(zip_path, extract_to):
    """Extrai o primeiro membro .gpkg do ZIP para ``extract_to``.

    Retorna True se um GPKG valido foi extraido, False caso contrario.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = [
                m for m in zf.namelist() if m.lower().endswith(".gpkg")
            ]
            if not members:
                return False
            gpkg_member = members[0]
            with zf.open(gpkg_member) as src, open(extract_to, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return _is_valid_gpkg_file(extract_to)
    except (zipfile.BadZipFile, OSError):
        return False


class DownloadMapeamentoHomologadoTask(SatIrrigaTask):
    """Download direto do GPKG consolidado de um mapeamento homologado."""

    def __init__(self, download_url, access_token, gpkg_output_path,
                 mapeamento_id, catalogo_meta=None):
        super().__init__(f"Download mapeamento homologado {mapeamento_id}")
        self._download_url = download_url
        self._token = access_token
        self._gpkg_path = gpkg_output_path
        self._mapeamento_id = mapeamento_id
        self._catalogo_meta = catalogo_meta or {}

    def run(self):
        temp_gpkg = None
        try:
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/geopackage+sqlite3",
            }

            existing_sidecar = read_sidecar(self._gpkg_path)
            existing_etag = existing_sidecar.get("etag")
            # Reaproveita cache apenas se o GPKG no disco ja for um SQLite
            # valido — evita revalidar arquivos corrompidos (ex.: ZIPs
            # antigos gravados como .gpkg) sem novo download.
            has_valid_cached_gpkg = (
                os.path.exists(self._gpkg_path)
                and _is_valid_gpkg_file(self._gpkg_path)
            )
            if existing_etag and has_valid_cached_gpkg:
                headers["If-None-Match"] = existing_etag

            self.signals.status_message.emit("Baixando mapeamento homologado...")
            self.setProgress(5)
            self._log(f"[HTTP] GET {self._download_url} (auth=True)")

            dl_resp = requests.get(
                self._download_url, headers=headers,
                stream=True, timeout=120,
            )
            self._log(f"[HTTP] {dl_resp.status_code} {self._download_url}")

            if dl_resp.status_code == 304 and has_valid_cached_gpkg:
                sidecar_data = existing_sidecar.copy()
                sidecar_data["downloadedAt"] = (
                    datetime.now(timezone.utc).isoformat()
                )
                sidecar_data["origin"] = DownloadOrigin.HOMOLOGACAO.value
                sidecar_data["readOnly"] = True
                write_sidecar(self._gpkg_path, sidecar_data)
                self.setProgress(100)
                self.signals.status_message.emit("Download concluido (cache)!")
                return True

            if dl_resp.status_code == 403:
                try:
                    err_body = dl_resp.json()
                    server_msg = err_body.get("message", "")
                except Exception:
                    server_msg = dl_resp.text[:200]
                self._exception = Exception(
                    server_msg
                    or "Acesso negado ao mapeamento homologado."
                )
                return False
            if dl_resp.status_code == 404:
                self._exception = Exception(
                    "Mapeamento homologado nao disponivel para download."
                )
                return False

            dl_resp.raise_for_status()

            temp_fd, temp_gpkg = tempfile.mkstemp(
                suffix=".gpkg", prefix="satirriga_mapeamento_"
            )
            total = int(dl_resp.headers.get("content-length", 0))
            downloaded = 0
            with os.fdopen(temp_fd, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    if self.isCanceled():
                        return False
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        self.setProgress(5 + int(downloaded * 85 / total))

            response_etag = dl_resp.headers.get("ETag", "")
            self.setProgress(92)

            # Inspeciona magic bytes: o servidor pode entregar o GPKG cru
            # ou empacotado em ZIP (ver Content-Type/cabecalho do endpoint).
            with open(temp_gpkg, "rb") as fh:
                head = fh.read(16)

            final_source = None
            if head.startswith(_GPKG_MAGIC):
                final_source = temp_gpkg
                self._log("[Download] Conteudo eh GeoPackage cru.")
            elif head.startswith(_ZIP_MAGIC):
                self._log("[Download] Conteudo eh ZIP — extraindo GPKG.")
                self.signals.status_message.emit(
                    "Extraindo GeoPackage do arquivo compactado..."
                )
                self.setProgress(94)
                extracted_fd, extracted_path = tempfile.mkstemp(
                    suffix=".gpkg", prefix="satirriga_extracted_",
                )
                os.close(extracted_fd)
                ok = _extract_gpkg_from_zip(temp_gpkg, extracted_path)
                if not ok:
                    if os.path.exists(extracted_path):
                        try:
                            os.unlink(extracted_path)
                        except OSError:
                            pass
                    self._exception = Exception(
                        "ZIP do servidor nao contem um GeoPackage valido."
                    )
                    return False
                final_source = extracted_path
            else:
                preview = head[:8].hex()
                self._exception = Exception(
                    f"Resposta do servidor nao e GeoPackage nem ZIP "
                    f"(magic={preview!r})."
                )
                return False

            self.setProgress(96)
            os.makedirs(os.path.dirname(self._gpkg_path), exist_ok=True)
            if os.path.exists(self._gpkg_path):
                os.remove(self._gpkg_path)
            shutil.move(final_source, self._gpkg_path)
            # Apos o move, temp_gpkg pode ou nao existir mais.
            if final_source != temp_gpkg and temp_gpkg and os.path.exists(temp_gpkg):
                try:
                    os.unlink(temp_gpkg)
                except OSError:
                    pass
            temp_gpkg = None

            sidecar_data = {}
            if self._catalogo_meta:
                sidecar_data.update(self._catalogo_meta)
            sidecar_data.update({
                "mapeamentoId": self._mapeamento_id,
                "origin": DownloadOrigin.HOMOLOGACAO.value,
                "readOnly": True,
                "etag": response_etag,
                "downloadedAt": datetime.now(timezone.utc).isoformat(),
            })
            write_sidecar(self._gpkg_path, sidecar_data)

            self.setProgress(100)
            self.signals.status_message.emit("Download concluido!")
            self._log(
                f"GPKG mapeamento homologado baixado: {self._gpkg_path}"
            )
            return True

        except requests.RequestException as e:
            self._exception = Exception(f"Erro de download: {e}")
            return False
        except Exception as e:
            self._exception = e
            return False
        finally:
            if temp_gpkg and os.path.exists(temp_gpkg):
                try:
                    os.unlink(temp_gpkg)
                except OSError:
                    pass
