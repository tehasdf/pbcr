"""Interop with the docker.io registry
"""
import requests

from pbcr.types import (
    ImageStorage,
    PullToken,
    Manifest,
    Digest,
    MediaType,
    ImageConfig,
    ImageLayer,
    Image,
)


REGISTRY_BASE = 'https://registry-1.docker.io'


def _get_pull_token(storage: ImageStorage, repo: str) -> PullToken:
    if token := storage.get_pull_token(registry='docker.io', repo=repo):
        return token

    resp = requests.get(
        'https://auth.docker.io/token?service=registry.docker.io&'
        f'scope=repository:{repo}:pull',
        timeout=10,
    )
    token_data = resp.json()
    # The 'issued_at' timestamp from Docker Hub API sometimes includes
    # microseconds which are not always handled consistently by datetime.fromisoformat.
    # Truncate to milliseconds and append 'Z' for UTC to ensure proper ISO 8601 format.
    if 'issued_at' in token_data and '.' in token_data['issued_at']:
        token_data['issued_at'] = token_data['issued_at'].split('.')[0] + 'Z'
    elif 'issued_at' in token_data and not token_data['issued_at'].endswith('Z'):
        token_data['issued_at'] += 'Z'

    token = PullToken.fromdict(token_data)

    storage.store_pull_token(registry='docker.io', repo=repo, token=token)
    return token


def _find_image_digest(
    repo: str,
    tag: str,
    token: PullToken,
    architecture: str = 'amd64',
) -> tuple[Digest, MediaType]:
    index_response = requests.get(
        f'{REGISTRY_BASE}/v2/{repo}/manifests/{tag}',
        headers={
            'Accept': ','.join([
                'application/vnd.docker.distribution.manifest.list.v2+json',
                'application/vnd.oci.image.index.v1+json',
            ]),
            'Authorization': f'Bearer {token}',
        },
        timeout=10,
    )
    index_data = index_response.json()
    for manifest_spec in index_data['manifests']:
        try:
            manifest_arch = manifest_spec['platform']['architecture']
        except KeyError:
            continue
        if manifest_arch == architecture:
            break
    else:
        raise ValueError(f'manifest for {architecture} not found')

    return manifest_spec['digest'], manifest_spec['mediaType']


def _get_image_manifest(
    storage: ImageStorage,
    repo: str,
    digest: Digest | None = None,
    mediatype: MediaType | None = None,
    token: PullToken | None = None,
) -> Manifest:
    if manifest := storage.get_manifest(
        registry='docker.io', repo=repo,
    ):
        return manifest
    if token is None:
        raise RuntimeError('need token to fetch manifest')
    if mediatype is None:
        raise RuntimeError('need mediatype to fetch manifest')
    if digest is None:
        raise RuntimeError('need digest to fetch manifest')
    manifest_response = requests.get(
        url=f'{REGISTRY_BASE}/v2/{repo}/manifests/{digest}',
        headers={
            'Accept': mediatype,
            'Authorization': f'Bearer {token}',
        },
        timeout=10,
    )
    manifest_data = manifest_response.json()
    manifest = Manifest(
        registry='docker.io',
        name=repo,
        digest=digest,
        config=(
            manifest_data['config']['digest'],
            manifest_data['config']['mediaType'],
        ),
        layers=[
            (layer['digest'], layer['mediaType'])
            for layer in manifest_data['layers']
        ],
    )
    storage.store_manifest(manifest=manifest)
    return manifest


def _get_image_layers(
    storage: ImageStorage,
    manifest: Manifest,
    token: PullToken | None = None,
) -> list[ImageLayer]:
    layers = []
    for layer_digest, layer_mediatype in manifest.layers:
        layer = storage.get_image_layer(manifest, layer_digest)
        if not layer:
            if token is None:
                raise RuntimeError('need token to fetch layers')

            layer_response = requests.get(
                f'{REGISTRY_BASE}/v2/{manifest.name}/blobs/{layer_digest}',
                headers={
                    'Accept': layer_mediatype,
                    'Authorization': f'Bearer {token}',
                },
                timeout=10,
            )
            layer_path = storage.store_image_layer(
                manifest,
                layer_digest,
                layer_response.content,
            )
            layer = ImageLayer(
                digest=layer_digest,
                path=layer_path,
            )
        layers.append(layer)
    return layers


def _get_image_config(
    storage: ImageStorage,
    manifest: Manifest,
    token: PullToken | None,
) -> ImageConfig:
    if image_config := storage.get_image_config(manifest):
        return image_config
    if token is None:
        raise RuntimeError('need token to fetch config')
    config_resp = requests.get(
        f'{REGISTRY_BASE}/v2/{manifest.name}/blobs/{manifest.config[0]}',
        headers={
            'Accept': manifest.config[1],
            'Authorization': f'Bearer {token}',
        },
        timeout=10,
    )

    config_data = config_resp.json()
    # Ensure all required fields for ImageConfig are present, providing defaults if missing
    image_config = ImageConfig(
        architecture=config_data.get('architecture', ''),
        os=config_data.get('os', ''),
        config=config_data.get('config', {}),
        rootfs=config_data.get('rootfs', {}),
        history=config_data.get('history', []),
    )
    storage.store_image_config(manifest, image_config)
    return image_config


def pull_image_from_docker(storage: ImageStorage, image_name: str) -> Image:
    """Fetch image from the docker.io registry"""
    repo, _, reference = image_name.partition(':')
    reference = reference or 'latest'
    token = _get_pull_token(storage, repo)

    if reference.startswith('sha256:'):
        digest = Digest(reference)
        mediatype = None
    else:
        digest, mediatype = _find_image_digest(repo, reference, token)

    manifest = _get_image_manifest(storage, repo, digest, mediatype, token)
    image_config = _get_image_config(storage, manifest, token)
    layers = _get_image_layers(storage, manifest, token)

    return Image(
        registry='docker.io',
        manifest=manifest,
        config=image_config,
        layers=layers,
    )


def load_docker_image(storage: ImageStorage, image_name: str) -> Image:
    """Load an image fetched from the docker.io registry"""
    repo, _, reference = image_name.partition(':')
    reference = reference or 'latest'

    manifest = _get_image_manifest(storage, repo, None, None, None)
    image_config = _get_image_config(storage, manifest, None)
    layers = _get_image_layers(storage, manifest)

    return Image(
        registry='docker.io',
        manifest=manifest,
        config=image_config,
        layers=layers,
    )
