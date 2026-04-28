from __future__ import annotations

import html
import importlib
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from xml.etree import ElementTree

from app.core.config import get_settings
from app.modules.content.models import ContentAsset, ContentObject

THUMBNAIL_MAX_WIDTH = 512
THUMBNAIL_MAX_HEIGHT = 512


class UnsupportedSnapshotError(Exception):
    pass


@dataclass(slots=True)
class GeneratedArtifact:
    filename: str
    mime_type: str
    path: Path

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size


class SnapshotArtifactGenerator:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root

    def generate(
        self,
        *,
        content_object: ContentObject,
        asset: ContentAsset | None,
        job_type: str,
    ) -> GeneratedArtifact:
        if job_type == "archive_org":
            raise UnsupportedSnapshotError("Archive.org snapshots require an external URL.")
        if asset is None:
            raise UnsupportedSnapshotError("This snapshot type requires a source asset.")

        source_path = self.storage_root / asset.storage_path
        output_dir = self.storage_root / content_object.storage_path / "snapshots" / asset.id
        output_dir.mkdir(parents=True, exist_ok=True)

        if job_type == "thumbnail":
            return self._generate_thumbnail(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
        if job_type == "thumbnail_text":
            return self._generate_thumbnail_text(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
        if job_type == "markdown":
            return self._generate_markdown(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
        if job_type == "screenshot":
            return self._generate_screenshot(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
        if job_type == "webpage_html":
            return self._generate_webpage_html(
                asset=asset, source_path=source_path, output_dir=output_dir
            )
        if job_type == "pdf":
            return self._generate_pdf(asset=asset, source_path=source_path, output_dir=output_dir)
        raise UnsupportedSnapshotError(f"Unsupported snapshot job type: {job_type}")

    def _generate_thumbnail(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
    ) -> GeneratedArtifact:
        if asset.media_type == "image":
            return self._render_image_thumbnail(
                source_path=source_path,
                output_dir=output_dir,
                filename="thumbnail.jpg",
            )
        if self._is_pdf(asset=asset, source_path=source_path):
            return self._render_pdf_first_page(
                source_path=source_path,
                output_dir=output_dir,
                filename="thumbnail.jpg",
            )
        preview_text = self._text_for_thumbnail_preview(asset=asset, source_path=source_path)
        if preview_text is not None:
            return self._render_text_thumbnail(
                output_dir=output_dir,
                filename="thumbnail.jpg",
                title=asset.filename,
                body=preview_text,
            )

        office_pdf = self._convert_office_to_pdf(source_path)
        if office_pdf is not None:
            return self._render_pdf_first_page(
                source_path=office_pdf,
                output_dir=output_dir,
                filename="thumbnail.jpg",
            )

        raise UnsupportedSnapshotError("No thumbnail renderer is available for this file.")

    def _generate_thumbnail_text(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
    ) -> GeneratedArtifact:
        preview_text = self._text_for_thumbnail_text(asset=asset, source_path=source_path)
        if preview_text is None:
            raise UnsupportedSnapshotError(
                "No text thumbnail extractor is available for this file."
            )
        path = output_dir / "thumbnail.txt"
        path.write_text(preview_text[:5000], encoding="utf-8")
        return GeneratedArtifact(filename="thumbnail.txt", mime_type="text/plain", path=path)

    def _generate_markdown(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
    ) -> GeneratedArtifact:
        text = self._extract_markdown_text(asset=asset, source_path=source_path)
        if text is None:
            raise UnsupportedSnapshotError("No markdown extractor is available for this file.")
        path = output_dir / "snapshot.md"
        path.write_text(f"# {asset.filename}\n\n{text.strip()}\n", encoding="utf-8")
        return GeneratedArtifact(filename="snapshot.md", mime_type="text/markdown", path=path)

    def _generate_screenshot(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
    ) -> GeneratedArtifact:
        if asset.media_type == "image":
            return self._copy_image_snapshot(
                source_path=source_path,
                output_dir=output_dir,
                filename="screenshot" + source_path.suffix.lower(),
                mime_type=asset.mime_type or "application/octet-stream",
            )
        return self._generate_thumbnail(asset=asset, source_path=source_path, output_dir=output_dir)

    def _generate_webpage_html(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
    ) -> GeneratedArtifact:
        suffix = source_path.suffix.lower()
        path = output_dir / "snapshot.html"
        if asset.mime_type == "text/html" or suffix in {".html", ".htm"}:
            path.write_bytes(source_path.read_bytes())
        else:
            text = self._text_for_preview(asset=asset, source_path=source_path)
            if text is None:
                raise UnsupportedSnapshotError(
                    "No HTML snapshot extractor is available for this file."
                )
            path.write_text(
                '<!doctype html><html><head><meta charset="utf-8">'
                f"<title>{html.escape(asset.filename)}</title></head><body><pre>"
                f"{html.escape(text)}</pre></body></html>",
                encoding="utf-8",
            )
        return GeneratedArtifact(filename="snapshot.html", mime_type="text/html", path=path)

    def _generate_pdf(
        self,
        *,
        asset: ContentAsset,
        source_path: Path,
        output_dir: Path,
    ) -> GeneratedArtifact:
        path = output_dir / "snapshot.pdf"
        if self._is_pdf(asset=asset, source_path=source_path):
            shutil.copyfile(source_path, path)
            return GeneratedArtifact(
                filename="snapshot.pdf", mime_type="application/pdf", path=path
            )

        office_pdf = self._convert_office_to_pdf(source_path)
        if office_pdf is not None:
            shutil.copyfile(office_pdf, path)
            return GeneratedArtifact(
                filename="snapshot.pdf", mime_type="application/pdf", path=path
            )

        text = self._text_for_preview(asset=asset, source_path=source_path)
        if text is None:
            raise UnsupportedSnapshotError("No PDF snapshot renderer is available for this file.")

        try:
            fitz = _load_fitz()
        except ImportError as exc:
            raise UnsupportedSnapshotError("PyMuPDF is required to render PDF snapshots.") from exc

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        rect = fitz.Rect(54, 54, 541, 788)
        page.insert_textbox(rect, text[:8000], fontsize=10, fontname="helv")
        doc.save(path)
        doc.close()
        return GeneratedArtifact(filename="snapshot.pdf", mime_type="application/pdf", path=path)

    def _render_pdf_first_page(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        filename: str,
    ) -> GeneratedArtifact:
        try:
            fitz = _load_fitz()
        except ImportError as exc:
            raise UnsupportedSnapshotError("PyMuPDF is required to render PDF thumbnails.") from exc

        doc = fitz.open(str(source_path))
        try:
            if doc.page_count == 0:
                raise UnsupportedSnapshotError("Cannot render an empty PDF.")
            page = doc[0]
            zoom = self._thumbnail_zoom(width=page.rect.width, height=page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            path = output_dir / filename
            pix.save(str(path))
            return GeneratedArtifact(filename=filename, mime_type="image/jpeg", path=path)
        finally:
            doc.close()

    def _render_image_thumbnail(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        filename: str,
    ) -> GeneratedArtifact:
        try:
            fitz = _load_fitz()
        except ImportError as exc:
            raise UnsupportedSnapshotError(
                "PyMuPDF is required to render image thumbnails."
            ) from exc

        try:
            doc = fitz.open(str(source_path))
        except Exception as exc:  # noqa: BLE001
            raise UnsupportedSnapshotError("Source image cannot be decoded.") from exc

        try:
            if doc.page_count == 0:
                raise UnsupportedSnapshotError("Cannot render an empty image.")
            page = doc[0]
            zoom = self._thumbnail_zoom(width=page.rect.width, height=page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            path = output_dir / filename
            pix.save(str(path))
            return GeneratedArtifact(filename=filename, mime_type="image/jpeg", path=path)
        finally:
            doc.close()

    @staticmethod
    def _thumbnail_zoom(*, width: float, height: float) -> float:
        if width <= 0 or height <= 0:
            raise UnsupportedSnapshotError("Cannot render a thumbnail for zero-sized content.")
        return min(THUMBNAIL_MAX_WIDTH / width, THUMBNAIL_MAX_HEIGHT / height, 1.0)

    def _render_text_thumbnail(
        self,
        *,
        output_dir: Path,
        filename: str,
        title: str,
        body: str,
    ) -> GeneratedArtifact:
        try:
            fitz = _load_fitz()
        except ImportError as exc:
            raise UnsupportedSnapshotError(
                "PyMuPDF is required to render text thumbnails."
            ) from exc

        doc = fitz.open()
        try:
            page = doc.new_page(width=595, height=842)
            page.insert_textbox(
                fitz.Rect(48, 42, 547, 92),
                title[:140],
                fontsize=16,
                fontname="helv",
            )
            page.insert_textbox(
                fitz.Rect(48, 116, 547, 800),
                body[:5000],
                fontsize=10,
                fontname="cour",
            )
            zoom = self._thumbnail_zoom(width=page.rect.width, height=page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            path = output_dir / filename
            pix.save(str(path))
            return GeneratedArtifact(filename=filename, mime_type="image/jpeg", path=path)
        finally:
            doc.close()

    def _copy_image_snapshot(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        filename: str,
        mime_type: str,
    ) -> GeneratedArtifact:
        path = output_dir / filename
        shutil.copyfile(source_path, path)
        return GeneratedArtifact(filename=filename, mime_type=mime_type, path=path)

    def _write_svg_preview(
        self,
        *,
        output_dir: Path,
        filename: str,
        title: str,
        body: str,
    ) -> GeneratedArtifact:
        path = output_dir / filename
        safe_title = html.escape(title[:80])
        safe_body = html.escape(body[:500])
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" '
            'viewBox="0 0 640 360">'
            '<rect width="640" height="360" rx="18" fill="#f4f6f8"/>'
            '<rect x="36" y="36" width="568" height="288" rx="12" fill="#ffffff"/>'
            '<text x="64" y="94" font-family="Arial, sans-serif" font-size="26" '
            f'font-weight="700" fill="#17202a">{safe_title}</text>'
            '<foreignObject x="64" y="124" width="512" height="150">'
            '<div xmlns="http://www.w3.org/1999/xhtml" '
            'style="font: 18px Arial, sans-serif; color: #34495e; line-height: 1.4; '
            f'white-space: pre-wrap; word-break: break-word;">{safe_body}</div>'
            "</foreignObject>"
            "</svg>",
            encoding="utf-8",
        )
        return GeneratedArtifact(filename=filename, mime_type="image/svg+xml", path=path)

    def _text_for_preview(self, *, asset: ContentAsset, source_path: Path) -> str | None:
        return self._extract_markdown_text(asset=asset, source_path=source_path)

    def _text_for_thumbnail_preview(self, *, asset: ContentAsset, source_path: Path) -> str | None:
        suffix = source_path.suffix.lower()
        text_mime_types = {
            "application/json",
            "text/csv",
            "text/html",
            "text/markdown",
            "text/plain",
        }
        if (
            asset.media_type == "text"
            or asset.mime_type in text_mime_types
            or suffix in {".csv", ".html", ".htm", ".json", ".md", ".markdown", ".txt"}
        ):
            return self._extract_markdown_text(asset=asset, source_path=source_path)
        return None

    def _text_for_thumbnail_text(self, *, asset: ContentAsset, source_path: Path) -> str | None:
        suffix = source_path.suffix.lower()
        if (
            asset.media_type == "text"
            or asset.mime_type in {"text/markdown", "text/plain"}
            or suffix in {".md", ".markdown", ".txt"}
        ):
            return self._extract_markdown_text(asset=asset, source_path=source_path)
        return None

    def _extract_markdown_text(self, *, asset: ContentAsset, source_path: Path) -> str | None:
        if asset.text_content:
            return asset.text_content

        suffix = source_path.suffix.lower()
        if asset.media_type == "text" or suffix in {".txt", ".md", ".markdown", ".csv", ".json"}:
            return self._decode_text(source_path)
        if asset.mime_type == "text/html" or suffix in {".html", ".htm"}:
            text = self._decode_text(source_path)
            return self._html_to_text(text) if text is not None else None
        if self._is_pdf(asset=asset, source_path=source_path):
            return self._extract_pdf_text(source_path)
        if suffix == ".docx":
            return self._extract_docx_text(source_path)
        return None

    @staticmethod
    def _is_pdf(*, asset: ContentAsset, source_path: Path) -> bool:
        return asset.mime_type == "application/pdf" or source_path.suffix.lower() == ".pdf"

    @staticmethod
    def _decode_text(source_path: Path) -> str | None:
        data = source_path.read_bytes()
        for encoding in ("utf-8", "utf-16", "cp1251"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    @staticmethod
    def _html_to_text(value: str) -> str:
        without_scripts = re.sub(
            r"<(script|style).*?</\1>",
            "",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )
        without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
        return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()

    @staticmethod
    def _extract_pdf_text(source_path: Path) -> str | None:
        try:
            fitz = _load_fitz()
        except ImportError:
            return None
        doc = fitz.open(str(source_path))
        try:
            return "\n".join(page.get_text("text") for page in doc).strip() or None
        finally:
            doc.close()

    @staticmethod
    def _extract_docx_text(source_path: Path) -> str | None:
        try:
            with zipfile.ZipFile(source_path) as archive:
                xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile):
            return None

        root = ElementTree.fromstring(xml)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        values = [node.text or "" for node in root.iter(f"{namespace}t")]
        text = "\n".join(value for value in values if value.strip()).strip()
        return text or None

    @staticmethod
    def _convert_office_to_pdf(source_path: Path) -> Path | None:
        command = get_settings().snapshot_office_converter_command
        if not command:
            return None

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            try:
                result = subprocess.run(
                    [
                        command,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(output_dir),
                        str(source_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                return None
            if result.returncode != 0:
                return None
            pdf_path = output_dir / f"{source_path.stem}.pdf"
            if not pdf_path.exists():
                return None
            stable_path = source_path.parent / f".converted-{source_path.stem}.pdf"
            shutil.copyfile(pdf_path, stable_path)
            return stable_path


def _load_fitz() -> Any:
    return importlib.import_module("fitz")
