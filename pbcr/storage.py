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
    def __init__(self, base: pathlib.Path):
        self._base = base

    def list_images(self) -> list[Image]:
        return []

    def get_pull_token(self, registry: str, repo: str) -> PullToken | None:
        tokens_file = self._base / 'pull_tokens.json'
        try:
            with tokens_file.open() as f:
                tokens = json.load(f)
        except (ValueError, IOError):
            tokens = {}

        try:
            token_data = tokens[registry][repo]
        except KeyError:
            return None
        token = PullToken.fromdict(token_data)

        if token.is_expired:
            del tokens[registry][repo]
            with tokens_file.open('w') as f:
                json.dump(tokens, f, indent=4)
            return None
        return token

    def store_pull_token(self, registry: str, repo: str, token: PullToken):
        tokens_file = self._base / 'pull_tokens.json'
        tokens_file.touch()
        with tokens_file.open('r+') as f:
            try:
                tokens = json.load(f)
            except ValueError:
                tokens = {}
            tokens.setdefault(registry, {})[repo] = token.asdict()
            f.seek(0)
            f.truncate()
            json.dump(tokens, f, indent=4)

    def get_manifest(
        self, registry: str, repo: str, digest: Digest,
    ) -> Manifest | None:
        manifest_file = self._base / registry / repo / 'manifest.json'
        try:
            with manifest_file.open() as f:
                return Manifest(**json.load(f))
        except (ValueError, IOError):
            return None

    def store_manifest(self, manifest: Manifest):
        manifest_file = (
            self._base /
            manifest.registry /
            manifest.name /
            'manifest.json'
        )
        if not manifest_file.parent.is_dir():
            manifest_file.parent.mkdir(parents=True)
        with manifest_file.open('w') as f:
            json.dump(manifest.asdict(), f, indent=4)

    def get_image_config(self, manifest: Manifest) -> ImageConfig | None:
        config_file = (
            self._base /
            manifest.registry /
            manifest.name /
            'config.json'
        )
        try:
            with config_file.open() as f:
                return ImageConfig(**json.load(f))
        except (ValueError, IOError):
            return None

    def store_image_config(self, manifest: Manifest, config: ImageConfig):
        config_file = (
            self._base /
            manifest.registry /
            manifest.name /
            'config.json'
        )
        with config_file.open('w') as f:
            json.dump(config.asdict(), f, indent=4)

    def get_image_layer(
        self, manifest: Manifest, digest: Digest,
    ) -> ImageLayer | None:
        layer_file = (
            self._base /
            manifest.registry /
            manifest.name /
            'layers' /
            str(digest).replace('sha256:', '')
        )
        if layer_file.exists():
            return ImageLayer(
                digest=digest,
                path=layer_file,
            )
        return None

    def store_image_layer(
        self, manifest: Manifest, digest: Digest, data: bytes,
    ) -> pathlib.Path:
        layer_dir = (
            self._base /
            manifest.registry /
            manifest.name /
            'layers' /
            str(digest).replace('sha256:', '')
        )
        if not layer_dir.is_dir():
            layer_dir.mkdir(parents=True)
        data_f = io.BytesIO(data)
        with tarfile.open(fileobj=data_f) as tf:
            tf.extractall(layer_dir)
        return layer_dir

    def make_container_dir(
        self, container_id: str, image: Image,
    ) -> pathlib.Path:
        container_chroot = (
            self._base /
            'containers' /
            container_id
        )
        if not container_chroot.is_dir():
            container_chroot.mkdir(parents=True)
        return container_chroot

    def get_container(self, container_id: str) -> Container | None:
        registry_path = (
            self._base /
            'containers.json'
        )
        with registry_path.open() as f:
            try:
                containers = json.load(f)
            except (IOError, ValueError):
                containers = {}
        if container_id not in containers:
            return None
        return Container(**containers[container_id])

    def store_container(self, container: Container):
        registry_path = (
            self._base /
            'containers.json'
        )
        registry_path.touch()
        with registry_path.open('r+') as f:
            try:
                containers = json.load(f)
            except (IOError, ValueError):
                containers = {}
            containers[container.id] = container.asdict()
            f.seek(0)
            f.truncate()
            json.dump(containers, f, indent=4)

    def remove_container(self, container: Container):
        registry_path = (
            self._base /
            'containers.json'
        )
        registry_path.touch()
        with registry_path.open('r+') as f:
            try:
                containers = json.load(f)
                del containers[container.id]
            except (IOError, ValueError, KeyError) as e:
                return
            f.seek(0)
            f.truncate()
            json.dump(containers, f, indent=4)

        shutil.rmtree(
            self._base / 'containers' / container.id,
            ignore_errors=True,
        )


def make_storage(
    base_path: pathlib.Path | str=pathlib.Path('~/.pbcr'),
    **kwargs,
) -> Storage:
    base_path = pathlib.Path(base_path).expanduser().absolute()
    if not base_path.is_dir():
        base_path.mkdir(parents=True)
    return FileStorage(base=base_path)
