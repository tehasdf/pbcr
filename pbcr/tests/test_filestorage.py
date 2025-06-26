"""File storage tests"""
from pathlib import Path

from pbcr.storage import FileImageStorage


def test_make_filestorage(tmp_path):
    """make_storage creates a FileStorage with an existing dir structure"""
    target = tmp_path / 'pbcr'
    assert not target.exists()
    storage = FileImageStorage.create(target)
    assert isinstance(storage, FileImageStorage)
    assert target.is_dir()


def test_no_images(tmp_path):
    """An empty storage returns no images"""
    storage = FileImageStorage(tmp_path / 'pbcr')
    assert not storage.list_images()
