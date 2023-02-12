from pbcr.filestorage import FileStorage


def test_no_images(tmpdir):
    fs = FileStorage(tmpdir)
    assert fs.list_images() == []
