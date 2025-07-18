"""Implementations of storage backends"""

import io
import json
import pathlib
import shutil
import tarfile

from pbcr.types import (
    PullToken,
    Manifest,
    Digest,
    ImageConfig,
    ImageLayer,
    Container,
    ImageSummary,
    Image,
)


class FileImageStorage:
    """A file-backed Storage, that puts its data in JSON files"""

    @classmethod
    def create(cls, base_path: pathlib.Path):
        """Create a new FileImageStorage at the given target path"""
        base_path = base_path.expanduser().absolute()
        if not base_path.is_dir():
            base_path.mkdir(parents=True)
        return cls(base=base_path)

    def __init__(self, base: pathlib.Path):
        self._base = base

    def _get_image_base_path(self, digest: Digest) -> pathlib.Path:
        """Constructs the base path for a given image digest."""
        return (
            self._base /
            'images' /
            str(digest).replace('sha256:', '')
        )

    def _load_images_json(self) -> dict[str, ImageSummary]:
        """Loads and returns the content of images.json."""
        images_path = self._base / 'images.json'
        try:
            with images_path.open('r') as images_file:
                images_data = json.load(images_file)
        except (ValueError, IOError):
            images_data = {}

        # Convert raw dict data to ImageSummary objects
        return {k: ImageSummary(**v) for k, v in images_data.items()}

    def list_images(self) -> list[ImageSummary]:
        """Return stored images"""
        images = self._load_images_json()
        # Return ImageSummary objects directly from images.json
        return list(images.values())

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
        self, registry: str, repo: str, reference: str | None = None
    ) -> Manifest | None:
        """Return the Manifest of the specified image, or None"""
        images = self._load_images_json()

        found_digest = None

        if reference and reference.startswith('sha256:'):
            # If reference is a digest, try to find it directly
            if reference in images:
                img_summary = images[reference]
                if img_summary.registry == registry and img_summary.name == repo:
                    found_digest = img_summary.digest
        else:
            # Otherwise, iterate and match by registry, name, and optionally tag
            for img_summary in images.values():
                if img_summary.registry == registry and img_summary.name == repo:
                    if reference is None or reference in img_summary.tags:
                        found_digest = img_summary.digest
                        break

        if found_digest:
            manifest_path = self._get_image_base_path(found_digest) / 'manifest.json'
            try:
                with manifest_path.open('r') as manifest_file:
                    return Manifest(**json.load(manifest_file))
            except (ValueError, IOError):
                return None
        return None

    def store_manifest(self, manifest: Manifest, tags: list[str] | None = None):
        """Store an OCI image Manifest"""
        manifest_path = self._get_image_base_path(manifest.digest) / 'manifest.json'
        if not manifest_path.parent.is_dir():
            manifest_path.parent.mkdir(parents=True)
        with manifest_path.open('w') as manifest_file:
            json.dump(manifest.asdict(), manifest_file, indent=4)
        images_path = self._base / 'images.json'
        images_path.touch()
        with images_path.open('r+') as images_file:
            try:
                images_data = json.load(images_file)
            except ValueError:
                images_data = {}
            # Store only digest, registry, name, and tags in images.json
            image_summary = ImageSummary(
                digest=manifest.digest,
                registry=manifest.registry,
                name=manifest.name,
                tags=tags if tags is not None else [],
            )
            images_data[str(manifest.digest)] = image_summary.asdict()
            images_file.seek(0)
            images_file.truncate()
            json.dump(images_data, images_file, indent=4)

    def get_image_config(self, manifest: Manifest) -> ImageConfig | None:
        """Get the ImageConfig for the image described by the Manifest"""
        config_path = self._get_image_base_path(manifest.digest) / 'config.json'
        try:
            with config_path.open() as config_file:
                return ImageConfig(**json.load(config_file))
        except (ValueError, IOError):
            return None

    def store_image_config(self, manifest: Manifest, config: ImageConfig):
        """Store the ImageConfig for the image described by the Manifest"""
        config_path = self._get_image_base_path(manifest.digest) / 'config.json'
        if not config_path.parent.is_dir():
            config_path.parent.mkdir(parents=True)
        with config_path.open('w') as config_file:
            json.dump(config.asdict(), config_file, indent=4)

    def get_image_layer(
        self, manifest: Manifest, digest: Digest,
    ) -> ImageLayer | None:
        """Layer from the image selected by Manifest, with the given digest"""
        layer_path = (
            self._get_image_base_path(manifest.digest) /
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
            self._get_image_base_path(manifest.digest) /
            'layers' /
            str(digest).replace('sha256:', '')
        )
        if not layer_dir.is_dir():
            layer_dir.mkdir(parents=True)
        data_f = io.BytesIO(data)
        with tarfile.open(fileobj=data_f) as layer_tar:
            layer_tar.extractall(layer_dir)
        return layer_dir

    def get_image(self, registry: str, repo: str, reference: str) -> Image | None:
        """
        Returns a full Image object (manifest, config, and layers) or None if not found.
        """
        manifest = self.get_manifest(registry, repo, reference)
        if not manifest:
            return None

        config = self.get_image_config(manifest)
        if not config:
            return None

        layers = []
        for layer_digest, _ in manifest.layers:
            layer = self.get_image_layer(manifest, layer_digest)
            if not layer:
                return None  # If any layer is missing, the image is incomplete
            layers.append(layer)

        return Image(
            registry=registry,
            manifest=manifest,
            config=config,
            layers=layers,
        )


class FileContainerStorage:
    """A file-backed Storage, that puts its data in JSON files"""
    @classmethod
    def create(cls, base_path: pathlib.Path):
        """Create a new FileContainerStorage at the given target path"""
        base_path = base_path.expanduser().absolute()
        if not base_path.is_dir():
            base_path.mkdir(parents=True)
        return cls(base=base_path)

    def __init__(self, base: pathlib.Path):
        self._base = base

    def make_container_dir(
        self, container_id: str,
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
        try:
            with registry_path.open('r+') as registry_file:
                containers = json.load(registry_file)
                containers[container.container_id] = container.asdict()
                registry_file.seek(0)
                registry_file.truncate()
                json.dump(containers, registry_file, indent=4)
        except (IOError, ValueError):
            containers = {}

    def remove_container(self, container: Container):
        """Remove the container from storage"""
        registry_path = (
            self._base /
            'containers.json'
        )
        registry_path.touch()
        try:
            with registry_path.open('r+') as registry_file:
                containers = json.load(registry_file)
                del containers[container.container_id]
                registry_file.seek(0)
                registry_file.truncate()
                json.dump(containers, registry_file, indent=4)
        except (IOError, ValueError, KeyError):
            return

        shutil.rmtree(
            self._base / 'containers' / container.container_id,
            ignore_errors=True,
        )

    def list_containers(self) -> list[Container]:
        """Return stored containers"""
        registry_path = (
            self._base /
            'containers.json'
        )
        try:
            with registry_path.open() as registry_file:
                containers = json.load(registry_file)
        except (IOError, ValueError):
            containers = {}
        return [Container(**c) for c in containers.values()]
