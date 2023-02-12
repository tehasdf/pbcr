import requests

from pbcr.types import (
    Storage,
    PullToken,
    Manifest,
    Digest,
    MediaType,
    ImageConfig,
    ImageLayer,
    Image,
)


REGISTRY_BASE = 'https://registry-1.docker.io'


def _get_pull_token(storage: Storage, repo: str) -> PullToken:
    if token := storage.get_pull_token(registry='docker.io', repo=repo):
        return token

    resp = requests.get(
        'https://auth.docker.io/token?service=registry.docker.io&'
        f'scope=repository:{repo}:pull',
    )
    token_data = resp.json()
    token_data['issued_at'] = token_data['issued_at'][:-4]
    token = PullToken.fromdict(token_data)

    storage.store_pull_token(registry='docker.io', repo=repo, token=token)
    return token


def _find_image_digest(
    repo: str,
    tag: str,
    token: PullToken,
    architecture: str='amd64',
) -> tuple[Digest, MediaType]:
    index_response = requests.get(
        f'{REGISTRY_BASE}/v2/{repo}/manifests/{tag}',
        headers={
            'Accept': ','.join([
                'application/vnd.docker.distribution.manifest.list.v2+json',
                'application/vnd.oci.image.index.v1+json',
            ]),
            'Authorization': f'Bearer {token}',
        }
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
    storage: Storage,
    repo: str,
    digest: Digest,
    mediatype: MediaType,
    token: PullToken,
) -> Manifest:
    if manifest := storage.get_manifest(
        registry='docker.io', repo=repo, digest=digest,
    ):
        return manifest
    manifest_response = requests.get(
        url = f'{REGISTRY_BASE}/v2/{repo}/manifests/{digest}',
        headers={
            'Accept': mediatype,
            'Authorization': f'Bearer {token}',
        }
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
    storage: Storage,
    manifest: Manifest,
    token: PullToken,
) -> list[ImageLayer]:
    layers = []
    for layer_digest, layer_mediatype in manifest.layers:
        layer = storage.get_image_layer(manifest, layer_digest)
        if not layer:
            layer_response = requests.get(
                f'{REGISTRY_BASE}/v2/{manifest.name}/blobs/{layer_digest}',
                headers={
                    'Accept': layer_mediatype,
                    'Authorization': f'Bearer {token}',
                }
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
    storage: Storage,
    manifest: Manifest,
    token: PullToken,
) -> ImageConfig:
    if image_config := storage.get_image_config(manifest):
        return image_config

    config_resp = requests.get(
        f'{REGISTRY_BASE}/v2/{manifest.name}/blobs/{manifest.config[0]}',
        headers={
            'Accept': manifest.config[1],
            'Authorization': f'Bearer {token}',
        }
    )

    config_data = config_resp.json()
    image_config = ImageConfig(**config_data)
    storage.store_image_config(manifest, image_config)
    return image_config


def pull_image_from_docker(storage: Storage, image_name: str) -> Image:
    repo, _, reference = image_name.partition(':')
    reference = reference or 'latest'
    token = _get_pull_token(storage, repo)

    if reference.startswith('sha256:'):
        digest = reference
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
