from dataclasses import dataclass

from pbcr.types import Digest


@dataclass
class Image:
    digest: Digest
