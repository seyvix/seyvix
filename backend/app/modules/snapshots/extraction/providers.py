from __future__ import annotations

import base64
import importlib
import math
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Any, Protocol

import httpx
from app.core.config import get_settings


class OcrProvider(Protocol):
    def extract_image_text(self, image_path: Path) -> str | None:
        raise NotImplementedError


class SttProvider(Protocol):
    def transcribe_media(self, media_path: Path) -> str | None:
        raise NotImplementedError


class VisionProvider(Protocol):
    def describe_image(self, image_path: Path) -> str | None:
        raise NotImplementedError

    def describe_video(self, video_path: Path, *, max_seconds: int) -> str | None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class DisabledOcrProvider:
    reason: str = "OCR provider is disabled."

    def extract_image_text(self, image_path: Path) -> str | None:
        return None


@dataclass(frozen=True, slots=True)
class DisabledSttProvider:
    reason: str = "Speech-to-text provider is disabled."

    def transcribe_media(self, media_path: Path) -> str | None:
        return None


@dataclass(frozen=True, slots=True)
class DisabledVisionProvider:
    reason: str = "Vision description provider is disabled."

    def describe_image(self, image_path: Path) -> str | None:
        return None

    def describe_video(self, video_path: Path, *, max_seconds: int) -> str | None:
        return None


@dataclass(frozen=True, slots=True)
class HttpOcrProvider:
    endpoint_url: str
    timeout_seconds: int

    def extract_image_text(self, image_path: Path) -> str | None:
        payload = {
            "filename": image_path.name,
            "content_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "languages": get_settings().snapshot_ocr_languages,
        }
        response = httpx.post(self.endpoint_url, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        text = data.get("text")
        return text.strip() if isinstance(text, str) and text.strip() else None


@dataclass(frozen=True, slots=True)
class HttpSttProvider:
    endpoint_url: str
    timeout_seconds: int

    def transcribe_media(self, media_path: Path) -> str | None:
        payload = {
            "filename": media_path.name,
            "content_base64": base64.b64encode(media_path.read_bytes()).decode("ascii"),
        }
        response = httpx.post(self.endpoint_url, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        text = data.get("text")
        return text.strip() if isinstance(text, str) and text.strip() else None


@dataclass(frozen=True, slots=True)
class HttpVisionProvider:
    endpoint_url: str
    timeout_seconds: int

    def describe_image(self, image_path: Path) -> str | None:
        return self._describe_media(image_path, kind="image", max_seconds=None)

    def describe_video(self, video_path: Path, *, max_seconds: int) -> str | None:
        return self._describe_media(video_path, kind="video", max_seconds=max_seconds)

    def _describe_media(
        self, source_path: Path, *, kind: str, max_seconds: int | None
    ) -> str | None:
        payload: dict[str, object] = {
            "kind": kind,
            "filename": source_path.name,
            "content_base64": base64.b64encode(source_path.read_bytes()).decode("ascii"),
        }
        if max_seconds is not None:
            payload["max_seconds"] = max_seconds
        response = httpx.post(self.endpoint_url, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        description = data.get("description") or data.get("text")
        return description.strip() if isinstance(description, str) and description.strip() else None


@dataclass(frozen=True, slots=True)
class OpenAICompatibleOcrProvider:
    base_url: str
    api_key: str | None
    model: str
    timeout_seconds: int
    max_image_bytes: int

    def extract_image_text(self, image_path: Path) -> str | None:
        if _file_too_large(image_path, self.max_image_bytes):
            return None
        payload = _vision_chat_payload(
            model=self.model,
            prompt=(
                "Extract all readable text from this image. Preserve line breaks and table-like "
                "structure where possible. Return only the extracted text."
            ),
            image_paths=[image_path],
        )
        response = httpx.post(
            _openai_url(self.base_url, "/chat/completions"),
            headers=_openai_headers(self.api_key),
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return _chat_completion_text(response.json())


@dataclass(frozen=True, slots=True)
class OpenAICompatibleSttProvider:
    base_url: str
    api_key: str | None
    model: str
    timeout_seconds: int
    max_media_seconds: int
    chunk_seconds: int

    def transcribe_media(self, media_path: Path) -> str | None:
        chunk_paths = self._extract_audio_chunks(media_path)
        try:
            transcripts = [
                transcript
                for chunk_path in chunk_paths
                if (transcript := self._transcribe_chunk(chunk_path))
            ]
            return "\n\n".join(transcripts) or None
        finally:
            _cleanup_temp_paths(chunk_paths)

    def _extract_audio_chunks(self, source_path: Path) -> list[Path]:
        output_dir = Path(mkdtemp(prefix="snapshot-stt-chunks-"))
        output_pattern = output_dir / "chunk-%03d.wav"
        command = ["ffmpeg", "-y", "-i", str(source_path)]
        if self.max_media_seconds >= 0:
            command.extend(["-t", str(self.max_media_seconds)])
        command.extend(
            [
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "segment",
                "-segment_time",
                str(max(self.chunk_seconds, 1)),
                "-reset_timestamps",
                "1",
                str(output_pattern),
            ]
        )
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            shutil.rmtree(output_dir, ignore_errors=True)
            return []
        if result.returncode != 0:
            shutil.rmtree(output_dir, ignore_errors=True)
            return []
        return sorted(output_dir.glob("chunk-*.wav"))

    def _transcribe_chunk(self, chunk_path: Path) -> str | None:
        with chunk_path.open("rb") as file_obj:
            response = httpx.post(
                _openai_url(self.base_url, "/audio/transcriptions"),
                headers=_openai_headers(self.api_key),
                data={"model": self.model},
                files={"file": (chunk_path.name, file_obj, "audio/wav")},
                timeout=self.timeout_seconds,
            )
        response.raise_for_status()
        data = response.json()
        text = data.get("text")
        return text.strip() if isinstance(text, str) and text.strip() else None


@dataclass(frozen=True, slots=True)
class OpenAICompatibleVisionProvider:
    base_url: str
    api_key: str | None
    model: str
    timeout_seconds: int
    max_image_bytes: int
    video_chunk_seconds: int
    video_frame_interval_seconds: int
    max_frames_per_request: int

    def describe_image(self, image_path: Path) -> str | None:
        if _file_too_large(image_path, self.max_image_bytes):
            return None
        payload = _vision_chat_payload(
            model=self.model,
            prompt=(
                "Describe this image for later semantic search. Include visible objects, "
                "people, UI, diagrams, text, context, and any searchable domain terms."
            ),
            image_paths=[image_path],
        )
        response = httpx.post(
            _openai_url(self.base_url, "/chat/completions"),
            headers=_openai_headers(self.api_key),
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return _chat_completion_text(response.json())

    def describe_video(self, video_path: Path, *, max_seconds: int) -> str | None:
        duration = self._probe_duration_seconds(video_path)
        ranges = self._video_ranges(max_seconds=max_seconds, duration_seconds=duration)
        descriptions: list[str] = []
        for index, (start_seconds, duration_seconds) in enumerate(ranges, start=1):
            frame_paths = self._extract_video_frames(
                video_path,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
            )
            try:
                if not frame_paths:
                    continue
                prompt = (
                    "Describe this video segment for later semantic search. These frames are "
                    f"sampled from {start_seconds}-{start_seconds + duration_seconds} seconds. "
                    "Mention visible objects, UI, actions, slides, scenes, and readable text."
                )
                payload = _vision_chat_payload(
                    model=self.model,
                    prompt=prompt,
                    image_paths=frame_paths,
                )
                response = httpx.post(
                    _openai_url(self.base_url, "/chat/completions"),
                    headers=_openai_headers(self.api_key),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                if text := _chat_completion_text(response.json()):
                    descriptions.append(
                        "Chunk "
                        f"{index} ({start_seconds}-{start_seconds + duration_seconds}s): {text}"
                    )
            finally:
                _cleanup_temp_paths(frame_paths)
        return "\n\n".join(descriptions) or None

    def _video_ranges(
        self, *, max_seconds: int, duration_seconds: float | None
    ) -> list[tuple[int, int]]:
        if max_seconds == 0:
            return []
        if max_seconds < 0:
            limit = (
                math.ceil(duration_seconds)
                if duration_seconds is not None
                else self.video_chunk_seconds
            )
        elif duration_seconds is None:
            limit = max_seconds
        else:
            limit = min(max_seconds, math.ceil(duration_seconds))
        if limit <= 0:
            return []
        chunk = max(self.video_chunk_seconds, 1)
        ranges: list[tuple[int, int]] = []
        start = 0
        while start < limit:
            ranges.append((start, min(chunk, limit - start)))
            start += chunk
        return ranges

    def _probe_duration_seconds(self, video_path: Path) -> float | None:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        try:
            return float(result.stdout.strip())
        except ValueError:
            return None

    def _extract_video_frames(
        self,
        source_path: Path,
        *,
        start_seconds: int,
        duration_seconds: int,
    ) -> list[Path]:
        output_dir = Path(mkdtemp(prefix="snapshot-video-frames-"))
        output_pattern = output_dir / "frame-%03d.jpg"
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_seconds),
            "-i",
            str(source_path),
            "-t",
            str(duration_seconds),
            "-vf",
            f"fps=1/{max(self.video_frame_interval_seconds, 1)}",
            "-frames:v",
            str(max(self.max_frames_per_request, 1)),
            str(output_pattern),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            shutil.rmtree(output_dir, ignore_errors=True)
            return []
        if result.returncode != 0:
            shutil.rmtree(output_dir, ignore_errors=True)
            return []
        return sorted(output_dir.glob("frame-*.jpg"))


@dataclass(frozen=True, slots=True)
class LocalTesseractOcrProvider:
    languages: str
    timeout_seconds: int

    def extract_image_text(self, image_path: Path) -> str | None:
        command = ["tesseract", str(image_path), "stdout"]
        if self.languages:
            command.extend(["-l", self.languages])
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None


@dataclass(frozen=True, slots=True)
class LocalWhisperSttProvider:
    model_name: str
    timeout_seconds: int
    max_media_seconds: int

    def transcribe_media(self, media_path: Path) -> str | None:
        audio_path = self._extract_audio(media_path)
        if audio_path is None:
            return None
        try:
            return self._transcribe_with_faster_whisper(
                audio_path
            ) or self._transcribe_with_whisper(audio_path)
        finally:
            audio_path.unlink(missing_ok=True)

    def _extract_audio(self, media_path: Path) -> Path | None:
        temp_file = NamedTemporaryFile(prefix="snapshot-audio-", suffix=".wav", delete=False)
        temp_file.close()
        audio_path = Path(temp_file.name)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(media_path),
        ]
        if self.max_media_seconds >= 0:
            command.extend(["-t", str(self.max_media_seconds)])
        command.extend(
            [
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(audio_path),
            ]
        )
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            audio_path.unlink(missing_ok=True)
            return None
        if result.returncode != 0 or not audio_path.exists():
            audio_path.unlink(missing_ok=True)
            return None
        return audio_path

    def _transcribe_with_faster_whisper(self, audio_path: Path) -> str | None:
        try:
            module = importlib.import_module("faster_whisper")
        except ImportError:
            return None
        model = module.WhisperModel(self.model_name, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path))
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return text or None

    def _transcribe_with_whisper(self, audio_path: Path) -> str | None:
        try:
            module = importlib.import_module("whisper")
        except ImportError:
            return None
        model = module.load_model(self.model_name)
        result = model.transcribe(str(audio_path))
        text = result.get("text") if isinstance(result, dict) else None
        return text.strip() if isinstance(text, str) and text.strip() else None


def build_ocr_provider() -> OcrProvider:
    settings = get_settings()
    if (
        settings.snapshot_ocr_provider == "openai_compatible"
        and settings.snapshot_ocr_openai_base_url
    ):
        return OpenAICompatibleOcrProvider(
            base_url=settings.snapshot_ocr_openai_base_url,
            api_key=settings.snapshot_ocr_openai_api_key,
            model=settings.snapshot_ocr_openai_model,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
            max_image_bytes=settings.snapshot_ocr_max_image_bytes,
        )
    if settings.snapshot_ocr_provider == "http" and settings.snapshot_ocr_http_url:
        return HttpOcrProvider(
            endpoint_url=settings.snapshot_ocr_http_url,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
        )
    if settings.snapshot_ocr_provider == "local":
        return LocalTesseractOcrProvider(
            languages=settings.snapshot_ocr_languages,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
        )
    return DisabledOcrProvider()


def build_stt_provider() -> SttProvider:
    settings = get_settings()
    if (
        settings.snapshot_stt_provider == "openai_compatible"
        and settings.snapshot_stt_openai_base_url
    ):
        return OpenAICompatibleSttProvider(
            base_url=settings.snapshot_stt_openai_base_url,
            api_key=settings.snapshot_stt_openai_api_key,
            model=settings.snapshot_stt_openai_model,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
            max_media_seconds=settings.snapshot_extraction_max_media_seconds,
            chunk_seconds=settings.snapshot_stt_chunk_seconds,
        )
    if settings.snapshot_stt_provider == "http" and settings.snapshot_stt_http_url:
        return HttpSttProvider(
            endpoint_url=settings.snapshot_stt_http_url,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
        )
    if settings.snapshot_stt_provider == "local":
        return LocalWhisperSttProvider(
            model_name=settings.snapshot_stt_model,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
            max_media_seconds=settings.snapshot_extraction_max_media_seconds,
        )
    return DisabledSttProvider()


def build_vision_provider() -> VisionProvider:
    settings = get_settings()
    if (
        settings.snapshot_vision_provider == "openai_compatible"
        and settings.snapshot_vision_openai_base_url
    ):
        return OpenAICompatibleVisionProvider(
            base_url=settings.snapshot_vision_openai_base_url,
            api_key=settings.snapshot_vision_openai_api_key,
            model=settings.snapshot_vision_openai_model,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
            max_image_bytes=settings.snapshot_vision_max_image_bytes,
            video_chunk_seconds=settings.snapshot_vision_video_chunk_seconds,
            video_frame_interval_seconds=settings.snapshot_vision_video_frame_interval_seconds,
            max_frames_per_request=settings.snapshot_vision_max_frames_per_request,
        )
    if settings.snapshot_vision_provider == "http" and settings.snapshot_vision_http_url:
        return HttpVisionProvider(
            endpoint_url=settings.snapshot_vision_http_url,
            timeout_seconds=settings.snapshot_extraction_timeout_seconds,
        )
    return DisabledVisionProvider()


def _openai_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _openai_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _vision_chat_payload(*, model: str, prompt: str, image_paths: list[Path]) -> dict[str, object]:
    content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _image_data_url(image_path)},
            }
        )
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
    }


def _image_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _chat_completion_text(data: dict[str, Any]) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None


def _file_too_large(path: Path, max_bytes: int) -> bool:
    return max_bytes >= 0 and path.stat().st_size > max_bytes


def _cleanup_temp_paths(paths: list[Path]) -> None:
    parents: set[Path] = set()
    for path in paths:
        parents.add(path.parent)
        path.unlink(missing_ok=True)
    for parent in parents:
        if parent.name.startswith(("snapshot-stt-chunks-", "snapshot-video-frames-")):
            shutil.rmtree(parent, ignore_errors=True)
