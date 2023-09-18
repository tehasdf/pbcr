"""Implementations of storage backends"""

import io
import json
import pathlib
import shutil
import tarfile

from pbcr.types import (
    Image,
    Storage,
    PullToken,
    Manifest,
    Digest,
    ImageConfig,
    ImageLayer,
    Container,
)


class FileStorage:
    """A file-backed Storage, that puts its data in JSON files"""
    def __init__(self, base: pathlib.Path):
        self._base = base

    def list_images(self) -> list[Manifest]:
        """Return stored images"""
        images_path = self._base / 'images.json'
        with images_path.open('r') as images_file:
            images = json.load(images_file)
        return [Manifest(**img) for img in images.values()]

    def get_pull_token(self, registry: str, repo: str) -> PullToken | None:
        """Look up a PullToken for the given registry + repo

        If there is no PullToken for that target stored, return None.
        """
        tokens_path = self._base / 'pull_tokens.json'
        try:
            with tokens_path.open() as tokens_file:
                tokens = json.load(tokens_file)
        except (ValueError, IOError):
            tokens = {}

        try:
            token_data = tokens[registry][repo]
        except KeyError:
            return None
        token = PullToken.fromdict(token_data)

        if token.is_expired:
            del tokens[registry][repo]
            with tokens_path.open('w') as tokens_file:
                json.dump(tokens, tokens_file, indent=4)
            return None
        return token

    def store_pull_token(self, registry: str, repo: str, token: PullToken):
        """Store up a PullToken for the given registry + repo"""
        tokens_path = self._base / 'pull_tokens.json'
        tokens_path.touch()
        with tokens_path.open('r+') as tokens_file:
            try:
                tokens = json.load(tokens_file)
            except ValueError:
                tokens = {}
            tokens.setdefault(registry, {})[repo] = token.asdict()
            tokens_file.seek(0)
            tokens_file.truncate()
            json.dump(tokens, tokens_file, indent=4)

    def get_manifest(
        self, registry: str, repo: str
    ) -> Manifest | None:
        """Return the Manifest of the specified image, or None"""
        manifest_path = (
            self._base /
            'images'/
            registry /
            repo /
            'manifest.json'
        )
        try:
            with manifest_path.open() as manifest_file:
                return Manifest(**json.load(manifest_file))
        except (ValueError, IOError):
            return None

    def store_manifest(self, manifest: Manifest):
        """Store an OCI image Manifest"""
        manifest_path = (
            self._base /
            'images' /
            manifest.registry /
            manifest.name /
            'manifest.json'
        )
        if not manifest_path.parent.is_dir():
            manifest_path.parent.mkdir(parents=True)
        with manifest_path.open('w') as manifest_file:
            json.dump(manifest.asdict(), manifest_file, indent=4)
        images_path = self._base / 'images.json'
        images_path.touch()
        with images_path.open('r+') as images_file:
            try:
                images = json.load(images_file)
            except ValueError:
                images = {}
            images[manifest.digest] = manifest.asdict()
            images_file.seek(0)
            images_file.truncate()
            json.dump(images, images_file, indent=4)

    def get_image_config(self, manifest: Manifest) -> ImageConfig | None:
        """Get the ImageConfig for the image described by the Manifest"""
        config_path = (
            self._base /
            'images' /
            manifest.registry /
            manifest.name /
            'config.json'
        )
        try:
            with config_path.open() as config_file:
                return ImageConfig(**json.load(config_file))
        except (ValueError, IOError):
            return None

    def store_image_config(self, manifest: Manifest, config: ImageConfig):
        """Store the ImageConfig for the image described by the Manifest"""
        config_path = (
            self._base /
            'images' /
            manifest.registry /
            manifest.name /
            'config.json'
        )
        with config_path.open('w') as config_file:
            json.dump(config.asdict(), config_file, indent=4)

    def get_image_layer(
        self, manifest: Manifest, digest: Digest,
    ) -> ImageLayer | None:
        """Layer from the image selected by Manifest, with the given digest"""
        layer_path = (
            self._base /
            'images' /
            manifest.registry /
            manifest.name /
            'layers' /
            str(digest).replace('sha256:', '')
        )
        if layer_path.exists():
            return ImageLayer(
                digest=digest,
                path=layer_path,
            )
        return None

    def store_image_layer(
        self, manifest: Manifest, digest: Digest, data: bytes,
    ) -> pathlib.Path:
        """Store a single image FS layer"""
        layer_dir = (
            self._base /
            'images' /
            manifest.registry /
            manifest.name /
            'layers' /
            str(digest).replace('sha256:', '')
        )
        if not layer_dir.is_dir():
            layer_dir.mkdir(parents=True)
        data_f = io.BytesIO(data)
        with tarfile.open(fileobj=data_f) as layer_tar:
            layer_tar.extractall(layer_dir)
        return layer_dir

    def make_container_dir(
        self, container_id: str, _: Image,
    ) -> pathlib.Path:
        """Prepare a directory for a new container"""
        container_chroot = (
            self._base /
            'containers' /
            container_id
        )
        if not container_chroot.is_dir():
            container_chroot.mkdir(parents=True)
        return container_chroot

    def get_container(self, container_id: str) -> Container | None:
        """Look up a container by its name"""
        registry_path = (
            self._base /
            'containers.json'
        )
        with registry_path.open() as registry_file:
            try:
                containers = json.load(registry_file)
            except (IOError, ValueError):
                containers = {}
        if container_id not in containers:
            return None
        return Container(**containers[container_id])

    def store_container(self, container: Container):
        """Store the container"""
        registry_path = (
            self._base /
            'containers.json'
        )
        registry_path.touch()
        with registry_path.open('r+') as registry_file:
            try:
                containers = json.load(registry_file)
            except (IOError, ValueError):
                containers = {}
            containers[container.container_id] = container.asdict()
            registry_file.seek(0)
            registry_file.truncate()
            json.dump(containers, registry_file, indent=4)

    def remove_container(self, container: Container):
        """Remove the container from storage"""
        registry_path = (
            self._base /
            'containers.json'
        )
        registry_path.touch()
        with registry_path.open('r+') as registry_file:
            try:
                containers = json.load(registry_file)
                del containers[container.container_id]
            except (IOError, ValueError, KeyError):
                return
            registry_file.seek(0)
            registry_file.truncate()
            json.dump(containers, registry_file, indent=4)

        shutil.rmtree(
            self._base / 'containers' / container.container_id,
            ignore_errors=True,
        )


def make_storage(
    base_path: pathlib.Path | str=pathlib.Path('~/.pbcr'),
    **_,
) -> Storage:
    """Create a Storage at the given target path"""
    base_path = pathlib.Path(base_path).expanduser().absolute()
    if not base_path.is_dir():
        base_path.mkdir(parents=True)
    return FileStorage(base=base_path)
