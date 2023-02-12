import typing

from dataclasses import dataclass


Digest = typing.NewType('Digest', str)


@dataclass
class Image:
    digest: Digest


class Storage(typing.Protocol):  # pragma: no cover
    def list_images(self) -> list[Image]:
        ...
