import typing
from datetime import datetime, timedelta

from dataclasses import dataclass


Digest = typing.NewType('Digest', str)


@dataclass
class Image:
    digest: Digest


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
        return self.issued_at + timedelta(seconds=self.expires_in)

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at


class Storage(typing.Protocol):  # pragma: no cover
    def get_pull_token(self, registry: str, repo: str) -> PullToken | None:
        ...

    def store_pull_token(self, registry: str, repo: str, token: PullToken):
        ...

    def list_images(self) -> list[Image]:
        ...
