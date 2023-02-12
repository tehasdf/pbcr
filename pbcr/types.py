import typing
from datetime import datetime, timedelta

from dataclasses import dataclass, asdict, fields


Digest = typing.NewType('Digest', str)
MediaType = typing.NewType('MediaType', str)


@dataclass
class Image:
    pass


@dataclass
class PullToken:
    token: str
    expires_in: int
    issued_at: datetime

    @classmethod
    def fromdict(cls, data) -> 'PullToken':
        return cls(
            token=data['token'],
            expires_in=data.get('expires_in', 300),
            issued_at=datetime.fromisoformat(data['issued_at']),
        )

    def asdict(self) -> dict[str, str | int]:
        return {
            'token': self.token,
            'expires_in': self.expires_in,
            'issued_at': self.issued_at.isoformat(),
        }

    @property
    def expires_at(self):
        # expire tokens 60 seconds before they normally would, so that
        # they are still usable for enough time for us to actually use them
        return self.issued_at + timedelta(seconds=self.expires_in - 60)

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    def __str__(self):
        return self.token


@dataclass
class Manifest:
    registry: str
    name: str
    digest: Digest
    config: tuple[Digest, MediaType]
    layers: list[tuple[Digest, MediaType]]

    def asdict(self):
        return asdict(self)


@dataclass(init=False)
class ImageConfig:
    architecture: str
    config: dict[str, typing.Any]
    container: str
    container_config: dict[str, typing.Any]
    history: list[dict]

    def __init__(self, **kwargs):
        # ignore additional passed-in fields
        attrs = {f.name for f in fields(self)}
        for k, v in kwargs.items():
            if k in attrs:
                setattr(self, k, v)

    def asdict(self):
        return asdict(self)


class Storage(typing.Protocol):  # pragma: no cover
    def get_pull_token(self, registry: str, repo: str) -> PullToken | None:
        ...

    def store_pull_token(self, registry: str, repo: str, token: PullToken):
        ...

    def list_images(self) -> list[Image]:
        ...

    def get_manifest(
        self, registry: str, repo: str, digest: Digest,
    ) -> Manifest | None:
        ...

    def store_manifest(self, manifest: Manifest):
        ...

    def get_image_config(self, manifest: Manifest) -> ImageConfig | None:
        ...

    def store_image_config(self, manifest: Manifest, config: ImageConfig):
        ...
