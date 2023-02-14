"""File storage tests"""
from pbcr.storage import FileStorage, make_storage


def test_make_filestorage(tmpdir):
    """make_storage creates a FileStorage with an existing dir structure"""
    target = tmpdir / 'pbcr'
    assert not target.exists()
    storage = make_storage(target)
    assert isinstance(storage, FileStorage)
    assert target.isdir()


def test_no_images(tmpdir):
    """An empty storage returns no images"""
    storage = FileStorage(tmpdir)
    assert not storage.list_images()
