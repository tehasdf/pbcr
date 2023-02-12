import pathlib

from pbcr.types import Image, Storage


class FileStorage:
    def __init__(self, base: pathlib.Path):
        self._base = base

    def list_images(self) -> list[Image]:
        return []


def make_storage(
    base_path: pathlib.Path | str=pathlib.Path('~/.pbcr'),
    **kwargs,
) -> Storage:
    base_path = pathlib.Path(base_path).expanduser().absolute()
    if not base_path.is_dir():
        base_path.mkdir()
    return FileStorage(base=base_path)
