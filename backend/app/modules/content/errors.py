from __future__ import annotations


class NoteNotFoundError(Exception):
    """The note (or an upload/asset referenced by the request) does not exist for this user."""


class FolderNotFoundError(Exception):
    pass


class ThumbnailPendingError(Exception):
    pass


class ThumbnailUnavailableError(Exception):
    pass
