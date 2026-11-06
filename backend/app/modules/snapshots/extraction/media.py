"""ffmpeg helpers (async subprocesses with timeouts; outputs go to the job's work dir)."""

from __future__ import annotations

from pathlib import Path

from app.core.logging import get_logger
from app.modules.snapshots.processes import ProcessTimeoutError, run_process

logger = get_logger(__name__)

FFMPEG = "ffmpeg"
_QUIET = ("-hide_banner", "-loglevel", "error", "-nostdin", "-y")


class MediaError(Exception):
    pass


async def _ffmpeg(args: list[str], *, timeout: float) -> None:
    try:
        result = await run_process([FFMPEG, *_QUIET, *args], timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaError("ffmpeg is not installed on the server.") from exc
    except ProcessTimeoutError as exc:
        raise MediaError(str(exc)) from exc
    if result.returncode != 0:
        logger.info("snapshot.ffmpeg.failed", returncode=result.returncode, stderr=result.stderr)
        raise MediaError("ffmpeg could not process this media file.")


async def video_frame(source: Path, out_path: Path, *, timeout: float) -> Path:
    """A representative frame from the first seconds of the video (JPEG)."""
    await _ffmpeg(
        ["-i", str(source), "-vf", "thumbnail=60", "-frames:v", "1", "-q:v", "3", str(out_path)],
        timeout=timeout,
    )
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise MediaError("Video frame could not be extracted.")
    return out_path


async def audio_chunks(
    source: Path, out_dir: Path, *, max_seconds: int, chunk_seconds: int, timeout: float
) -> list[Path]:
    """Mono 16 kHz MP3 chunks (small uploads, well under transcription API size limits)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    args = ["-i", str(source)]
    if max_seconds > 0:
        args += ["-t", str(max_seconds)]
    args += [
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k",
        "-f", "segment", "-segment_time", str(max(chunk_seconds, 30)), "-reset_timestamps", "1",
        str(out_dir / "chunk-%03d.mp3"),
    ]  # fmt: skip
    await _ffmpeg(args, timeout=timeout)
    return sorted(out_dir.glob("chunk-*.mp3"))


async def video_frames(
    source: Path,
    out_dir: Path,
    *,
    max_seconds: int,
    interval_seconds: int,
    timeout: float,
) -> list[Path]:
    """One downscaled JPEG frame every `interval_seconds` over the first `max_seconds`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    interval = max(interval_seconds, 1)
    max_frames = max(max_seconds // interval, 1)
    await _ffmpeg(
        [
            "-t",
            str(max_seconds),
            "-i",
            str(source),
            "-vf",
            f"fps=1/{interval},scale='min(768,iw)':-2",
            "-frames:v",
            str(max_frames),
            "-q:v",
            "5",
            str(out_dir / "frame-%04d.jpg"),
        ],  # fmt: skip
        timeout=timeout,
    )
    return sorted(out_dir.glob("frame-*.jpg"))
