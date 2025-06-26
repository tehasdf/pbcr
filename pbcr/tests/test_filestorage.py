"""File storage tests"""
from pathlib import Path

from pbcr.storage import FileImageStorage


def test_make_filestorage(tmpdir):
    """make_storage creates a FileStorage with an existing dir structure"""
    target = Path(tmpdir) / 'pbcr'
    assert not target.exists()
    storage = FileImageStorage.create(target)
    assert isinstance(storage, FileImageStorage)
    assert target.is_dir()


def test_no_images(tmpdir):
    """An empty storage returns no images"""
    storage = FileImageStorage(Path(tmpdir))
    assert not storage.list_images()
