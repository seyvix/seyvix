"""Storage key layout.

Everything that belongs to one content object lives under `objects/{content_object_id}/`
(originals, manifests, snapshot artifacts), so hard delete is a single `delete_prefix`.
Pending uploads live under `uploads/{owner_user_id}/{upload_id}/` until consumed or expired.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from unicodedata import normalize

OBJECTS_PREFIX = "objects/"
UPLOADS_PREFIX = "uploads/"

_UNSAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,16}$")


def safe_file_name(value: str) -> str:
    normalized = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = _UNSAFE_NAME_RE.sub("-", normalized).strip(".-")
    return normalized[:200] or "file"


def file_suffix(filename: str) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    return suffix if _SUFFIX_RE.match(suffix) else ".bin"


def object_prefix(content_object_id: str) -> str:
    return f"{OBJECTS_PREFIX}{safe_file_name(content_object_id)}/"


def object_key(content_object_id: str, *parts: str) -> str:
    return object_prefix(content_object_id) + "/".join(safe_file_name(part) for part in parts)


def asset_key(content_object_id: str, asset_id: str, filename: str) -> str:
    return object_key(content_object_id, "assets", asset_id, f"original{file_suffix(filename)}")


def asset_dir(asset_storage_key: str) -> str:
    """Directory (prefix, ends with `/`) that holds an asset's original and its artifacts."""
    head, sep, _ = asset_storage_key.rpartition("/")
    if not sep or not head.startswith(OBJECTS_PREFIX):
        raise ValueError(f"not an asset key: {asset_storage_key!r}")
    return f"{head}/"


def asset_artifact_key(asset_storage_key: str, *parts: str) -> str:
    """Key for a derived file (snapshot artifact) of an asset, stored next to the original."""
    return (
        asset_dir(asset_storage_key)
        + "snapshots/"
        + "/".join(safe_file_name(part) for part in parts)
    )


def object_id_from_key(key: str) -> str | None:
    """`objects/{id}/...` -> id (the object the key was created for)."""
    if not key.startswith(OBJECTS_PREFIX):
        return None
    object_id, sep, _ = key[len(OBJECTS_PREFIX) :].partition("/")
    return object_id if sep and object_id else None


def manifest_key(content_object_id: str) -> str:
    return object_key(content_object_id, "manifest.json")


def upload_owner_prefix(owner_user_id: str) -> str:
    return f"{UPLOADS_PREFIX}{safe_file_name(owner_user_id)}/"


def upload_prefix(owner_user_id: str, upload_id: str) -> str:
    return f"{upload_owner_prefix(owner_user_id)}{safe_file_name(upload_id)}/"


def upload_key(owner_user_id: str, upload_id: str, filename: str) -> str:
    return upload_prefix(owner_user_id, upload_id) + safe_file_name(filename)
