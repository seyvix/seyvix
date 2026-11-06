"""Office document → PDF via headless LibreOffice (isolated profile, killed as a group)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.core.config import Settings
from app.core.logging import get_logger
from app.modules.snapshots.processes import ProcessTimeoutError, run_process

logger = get_logger(__name__)

OfficeConversionFailure = Literal["disabled", "no_command", "timeout", "exit_error", "no_output"]
_IWORK_EXTS = frozenset({".key", ".pages", ".numbers"})


@dataclass(frozen=True, slots=True)
class OfficeConversionResult:
    pdf_path: Path | None
    failure_kind: OfficeConversionFailure | None = None
    stderr_tail: str = ""


async def convert_office_to_pdf(
    source: Path, work_dir: Path, settings: Settings
) -> OfficeConversionResult:
    """Convert once per job; callers reuse the PDF for thumbnail, PDF artifact and text.

    Each run gets its own LibreOffice profile (`-env:UserInstallation`) inside `work_dir`, so
    concurrent conversions never share or lock a profile, and the work dir cleanup removes it.
    """
    command = settings.snapshot_office_converter_command
    if not settings.snapshot_office_conversion_enabled:
        return OfficeConversionResult(None, "disabled")
    if not command:
        return OfficeConversionResult(None, "no_command")
    out_dir = work_dir / "office-pdf"
    profile_dir = work_dir / "office-profile"
    out_dir.mkdir(exist_ok=True)
    timeout = settings.snapshot_office_converter_timeout_seconds
    if not source.resolve().is_relative_to(work_dir.resolve()):
        # LibreOffice may drop lock files next to its input: never let it write into storage.
        link = work_dir / f"office-input{source.suffix}"
        link.symlink_to(source.resolve())
        source = link
    try:
        result = await run_process(
            [
                command,
                f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                "--headless",
                "--invisible",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(source),
            ],
            timeout=timeout,
            env={"HOME": str(profile_dir)},
        )
    except FileNotFoundError:
        logger.warning("snapshot.office.no_command", command=command)
        return OfficeConversionResult(None, "no_command")
    except ProcessTimeoutError as exc:
        logger.warning("snapshot.office.timeout", filename=source.name, timeout_seconds=timeout)
        return OfficeConversionResult(None, "timeout", str(exc))
    if result.returncode != 0:
        logger.warning(
            "snapshot.office.exit_error",
            filename=source.name,
            returncode=result.returncode,
            stderr_tail=result.stderr[-800:],
        )
        return OfficeConversionResult(None, "exit_error", result.stderr[-800:])
    pdf_path = out_dir / f"{source.stem}.pdf"
    if not pdf_path.is_file():
        logger.warning("snapshot.office.no_output", filename=source.name)
        return OfficeConversionResult(None, "no_output", result.stderr[-800:])
    return OfficeConversionResult(pdf_path)


def office_failure_message(
    *, asset_filename: str, result: OfficeConversionResult, timeout_seconds: int
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
    if result.failure_kind in {"no_command", "disabled"}:
        return "Конвертер офисных файлов недоступен на сервере."
    return (
        "Не удалось преобразовать файл в PDF. Попробуй сохранить документ "
        "в .pdf и загрузить повторно."
    )
