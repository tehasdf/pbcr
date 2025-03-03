"""Type definitions

Project-wide type definitions, and utility types, are declared here.
"""

import pathlib
import typing
from datetime import datetime, timedelta, timezone

from dataclasses import dataclass, asdict, field, fields


Digest = typing.NewType('Digest', str)
MediaType = typing.NewType('MediaType', str)


@dataclass
class PullToken:
    """PullToken is an OCI registry access token for pulling images"""
    token: str
    expires_in: int
    issued_at: datetime

    @classmethod
    def fromdict(cls, data) -> 'PullToken':
        """Create a PullToken from a dict, as returned by the registry auth"""
        return cls(
            token=data['token'],
            expires_in=data.get('expires_in', 300),
            issued_at=(
                datetime.fromisoformat(data['issued_at'])
                .replace(tzinfo=timezone.utc)
            ),
        )

    def asdict(self) -> dict[str, str | int]:
        """Serialize the token.

        Custom implementation instead of asdict, so that the timestamp is
        stringified, for easy JSON storage.
        """
        return {
            'token': self.token,
            'expires_in': self.expires_in,
            'issued_at': self.issued_at.isoformat(),
        }

    @property
    def expires_at(self):
        """Timestamp marking the expiration date of this token"""
        # expire tokens 60 seconds before they normally would, so that
        # they are still usable for enough time for us to actually use them
        return self.issued_at + timedelta(seconds=self.expires_in - 60)

    @property
    def is_expired(self):
        """Has this token already expired?"""
        return datetime.now(timezone.utc) > self.expires_at

    def __str__(self):
        return self.token


@dataclass
class Manifest:
    """An OCI Image manifest"""

    registry: str
    name: str
    digest: Digest
    config: tuple[Digest, MediaType]
    layers: list[tuple[Digest, MediaType]]

    def asdict(self):
        """Serialize the manifest"""
        return asdict(self)


@dataclass(init=False)
class ImageConfig:
    """An OCI image config.

    This is part of an OCI image, with container config info, like
    command, entrypoint, env, etc.
    The other part of an OCI image, that are usually bundled together
    with ImageConfig, are FS layers.
    """
    architecture: str
    config: dict[str, typing.Any]
    history: list[dict]

    def __init__(self, **kwargs):
        # ignore additional passed-in fields
        attrs = {f.name for f in fields(self)}
        for k, val in kwargs.items():
            if k in attrs:
                setattr(self, k, val)

    def asdict(self):
        """Serialize the ImageConfig"""
        return asdict(self)


@dataclass
class ImageLayer:
    """A single FS layer of an OCI image"""
    digest: Digest
    path: pathlib.Path


@dataclass
class Image:
    """Bundled information about a single OCI image"""
    registry: str
    manifest: Manifest
    config: ImageConfig
    layers: list[ImageLayer]


@dataclass
class Container:
    """Description of a PBCR container"""
    container_id: str
    pid: int | None
    image_registry: str
    image_name: str

    def asdict(self):
        """Serialize the Container"""
        return asdict(self)


class ImageStorage(typing.Protocol):
    """Methods that an image data storage must implement"""
    def get_pull_token(self, registry: str, repo: str) -> PullToken | None:
        """Look up a PullToken for the given registry + repo

        If there is no PullToken for that target stored, return None.
        """

    def store_pull_token(self, registry: str, repo: str, token: PullToken):
        """Store up a PullToken for the given registry + repo"""

    def list_images(self) -> list[Manifest]:
        """Return all Images in this storage"""
        raise NotImplementedError

    def get_manifest(
        self, registry: str, repo: str,
    ) -> Manifest | None:
        """Return the Manifest of the specified image, or None"""

    def store_manifest(self, manifest: Manifest):
        """Store an OCI image Manifest"""

    def get_image_config(self, manifest: Manifest) -> ImageConfig | None:
        """Get the ImageConfig for the image described by the Manifest"""

    def store_image_config(
        self,
        manifest: Manifest,
        config: ImageConfig,
    ):
        """Store the ImageConfig for the image described by the Manifest"""

    def get_image_layer(
        self, manifest: Manifest, digest: Digest,
    ) -> ImageLayer | None:
        """Layer from the image selected by Manifest, with the given digest"""

    def store_image_layer(
        self,
        manifest: Manifest,
        digest: Digest,
        data: bytes,
    ) -> pathlib.Path:
        """Store a single image FS layer"""
        raise NotImplementedError


class ContainerStorage(typing.Protocol):
    """Methods that a container data storage must implement"""
    def make_container_dir(
        self, container_id: str,
    ) -> pathlib.Path:
        """Prepare a directory for a new container"""
        raise NotImplementedError

    def get_container(self, container_id: str) -> Container | None:
        """Look up a container by its name"""

    def store_container(self, container: Container):
        """Store the container"""

    def remove_container(self, container: Container):
        """Remove the container from storage"""

    def list_containers(self) -> list[Container]:
        """List all containers in storage"""
        raise NotImplementedError


@dataclass
class ContainerConfig:
    """Settings for running a container"""
    image_name: str
    entrypoint: str = field(default='')
    command: str = field(default='')
    container_name: str | None = None
    daemon: bool = False
    volumes: list[str] | None = None
    remove: bool = False
