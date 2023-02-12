import json
import pathlib
import tarfile

from pbcr.types import (
    Image,
    Storage,
    PullToken,
    Manifest,
    Digest,
    ImageConfig,
    ImageLayer,
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
        with tokens_file.open('w+') as f:
            try:
                tokens = json.load(f)
            except ValueError:
                tokens = {}
            tokens.setdefault(registry, {})[repo] = token.asdict()
            f.seek(0)
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
            str(digest)
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
        layer_file = (
            self._base /
            manifest.registry /
            manifest.name /
            'layers' /
            str(digest)
        )
        if not layer_file.parent.is_dir():
            layer_file.parent.mkdir(parents=True)
        with layer_file.open('wb') as f:
            f.write(data)
        return layer_file

    def make_container_chroot(
        self, container_id: str, image: Image,
    ) -> pathlib.Path:
        container_chroot = (
            self._base /
            'containers' /
            container_id
        )
        if not container_chroot.is_dir():
            container_chroot.mkdir(parents=True)
        for layer in image.layers:
            with tarfile.open(layer.path) as tf:
                tf.extractall(container_chroot)
        return container_chroot


def make_storage(
    base_path: pathlib.Path | str=pathlib.Path('~/.pbcr'),
    **kwargs,
) -> Storage:
    base_path = pathlib.Path(base_path).expanduser().absolute()
    if not base_path.is_dir():
        base_path.mkdir(parents=True)
    return FileStorage(base=base_path)
