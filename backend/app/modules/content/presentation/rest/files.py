"""HTTP responses for stored files: sendfile on the local backend, ranged streaming on S3."""

from __future__ import annotations

from email.utils import format_datetime
from urllib.parse import quote

from fastapi import Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.api.errors import AppError
from app.platform.storage.service import StorageBackend, StorageObjectNotFoundError

# Asset ids are immutable (a new upload gets a new id), so browsers may cache for a day.
IMMUTABLE_FILE_CACHE = "private, max-age=86400"
# Files rewritten in place (text assets) must be revalidated with the ETag.
MUTABLE_FILE_CACHE = "private, no-cache"
_VARY = "Authorization, Cookie"


class _InvalidRange(Exception):
    pass


def content_disposition(filename: str, disposition: str = "inline") -> str:
    fallback = filename.encode("ascii", "ignore").decode("ascii").strip() or "file"
    fallback = fallback.replace("\\", "_").replace("/", "_").replace('"', "'")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if header is None:
        return None
    value = header.strip()
    if not value.startswith("bytes=") or "," in value:
        raise _InvalidRange
    start_text, separator, end_text = value.removeprefix("bytes=").strip().partition("-")
    if separator != "-" or (not start_text and not end_text) or size <= 0:
        raise _InvalidRange
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            suffix = int(end_text)
            if suffix <= 0:
                raise _InvalidRange
            start, end = max(size - suffix, 0), size - 1
    except ValueError as exc:
        raise _InvalidRange from exc
    if start < 0 or end < start or start >= size:
        raise _InvalidRange
    return start, min(end, size - 1)


def _not_found() -> AppError:
    return AppError(
        status_code=status.HTTP_404_NOT_FOUND, code="file_not_found", message="File not found."
    )


async def storage_file_response(
    request: Request,
    storage: StorageBackend,
    *,
    key: str,
    filename: str,
    media_type: str,
    cache_control: str = IMMUTABLE_FILE_CACHE,
    disposition: str = "inline",
) -> Response:
    headers = {
        "Cache-Control": cache_control,
        "Vary": _VARY,
        "Content-Disposition": content_disposition(filename, disposition),
        "X-Content-Type-Options": "nosniff",
    }
    local = storage.local_path(key)
    if local is not None:
        if not await storage.exists(key):
            raise _not_found()
        # Starlette handles Range/If-Range, ETag and Last-Modified and uses sendfile.
        return FileResponse(local, media_type=media_type, headers=headers)

    try:
        info = await storage.stat(key)
    except StorageObjectNotFoundError as exc:
        raise _not_found() from exc
    etag = f'"{info.etag}"'
    headers.update(
        {
            "ETag": etag,
            "Last-Modified": format_datetime(info.modified_at, usegmt=True),
            "Accept-Ranges": "bytes",
        }
    )
    if etag in {tag.strip() for tag in request.headers.get("if-none-match", "").split(",")}:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    range_header = request.headers.get("range")
    if request.headers.get("if-range") not in (None, etag):
        range_header = None
    try:
        bounds = _parse_range(range_header, info.size_bytes)
    except _InvalidRange:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{info.size_bytes}"},
        )
    if bounds is None:
        start, end, status_code = 0, info.size_bytes - 1, status.HTTP_200_OK
    else:
        (start, end), status_code = bounds, status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{end}/{info.size_bytes}"
    length = max(end - start + 1, 0)
    headers["Content-Length"] = str(length)
    if length == 0:
        return Response(status_code=status_code, media_type=media_type, headers=headers)
    return StreamingResponse(
        storage.iter_bytes(key, start, length),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )
