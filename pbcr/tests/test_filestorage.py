from pbcr.storage import FileStorage, make_storage


def test_make_filestorage(tmpdir):
    target = tmpdir / 'pbcr'
    assert not target.exists()
    fs = make_storage(target)
    assert isinstance(fs, FileStorage)
    assert target.isdir()


def test_no_images(tmpdir):
    fs = FileStorage(tmpdir)
    assert fs.list_images() == []
