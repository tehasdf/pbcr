import pathlib

from pbcr.images import Image


class FileStorage:
    def __init__(self, base: pathlib.Path):
        self._base = base

    def list_images(self) -> list[Image]:
        return []
