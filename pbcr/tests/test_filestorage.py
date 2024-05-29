"""File storage tests"""
from pbcr.storage import FileImageStorage


def test_make_filestorage(tmpdir):
    """make_storage creates a FileStorage with an existing dir structure"""
    target = tmpdir / 'pbcr'
    assert not target.exists()
    storage = FileImageStorage.create(target)
    assert isinstance(storage, FileImageStorage)
    assert target.isdir()


def test_no_images(tmpdir):
    """An empty storage returns no images"""
    storage = FileImageStorage(tmpdir)
    assert not storage.list_images()
