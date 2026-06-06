from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

OfficeConversionFailure = Literal["no_command", "timeout", "exit_error", "no_output"]


@dataclass(frozen=True)
class OfficeConversionResult:
    pdf_path: Path | None
    failure_kind: OfficeConversionFailure | None = None
    stderr_tail: str = ""

    @property
    def ok(self) -> bool:
        return self.pdf_path is not None


_IWORK_EXTS = frozenset({".key", ".pages", ".numbers"})


def office_failure_message(
    *,
    asset_filename: str,
    result: OfficeConversionResult,
    timeout_seconds: int,
) -> str:
    suffix = Path(asset_filename).suffix.lower()
    if suffix in _IWORK_EXTS and result.failure_kind in {"exit_error", "no_output"}:
        return (
            "Файлы Apple Keynote / Pages / Numbers поддерживаются частично. "
            "Экспортируй файл в PDF из приложения и загрузи снова."
        )
    if result.failure_kind == "timeout":
        return (
            f"Конвертация заняла больше {timeout_seconds} секунд и была отменена. "
            "Файл слишком сложный или слишком большой."
        )
    if result.failure_kind == "no_command":
        return "Конвертер офисных файлов недоступен на сервере."
    return (
        "Не удалось преобразовать файл в PDF. Попробуй сохранить документ "
        "в .pdf и загрузить повторно."
    )
