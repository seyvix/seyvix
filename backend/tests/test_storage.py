from pathlib import Path

import pytest

from app.platform.storage.keys import asset_artifact_key, asset_dir, asset_key, object_prefix
from app.platform.storage.local import LocalVolumeStorage
from app.platform.storage.service import InvalidStorageKeyError, StorageObjectNotFoundError


async def test_local_storage_roundtrip_ranges_and_prefix_delete(tmp_path: Path) -> None:
    storage = LocalVolumeStorage(tmp_path / "root")
    source = tmp_path / "source.bin"
    source.write_bytes(b"0123456789")
    key = asset_key("obj-1", "asset-1", "Report Final.PDF")
    assert key == "objects/obj-1/assets/asset-1/original.pdf"

    stored = await storage.put_file(key, source, "application/pdf")
    assert stored.size_bytes == 10
    assert stored.checksum.startswith("sha256:")
    assert await storage.get_bytes(key) == b"0123456789"
    assert b"".join([chunk async for chunk in storage.iter_bytes(key, 2, 4)]) == b"2345"
    assert (await storage.stat(key)).size_bytes == 10
    assert storage.local_path(key) == (tmp_path / "root" / key).resolve()

    artifact = asset_artifact_key(key, "thumbnail", "thumb.webp")
    assert artifact.startswith(asset_dir(key))
    await storage.put_bytes(artifact, b"thumb", "image/webp")
    await storage.move(artifact, artifact + ".moved")
    assert not await storage.exists(artifact)

    assert await storage.list_prefixes("objects/") == ["obj-1"]
    assert await storage.delete_prefix(object_prefix("obj-1")) == 2
    assert not await storage.exists(key)
    assert not (tmp_path / "root" / "objects").exists()
    with pytest.raises(StorageObjectNotFoundError):
        await storage.stat(key)


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "dir/"])
def test_storage_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        LocalVolumeStorage(tmp_path).local_path(key)
