"""Interop with the docker.io registry
"""
import contextlib
import pathlib

import httpx

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
REQUEST_TIMEOUT = 30


class TokenRequiredError(Exception):
    """Custom exception raised when a token is required but not provided."""


# Removed _get_async_client context manager as client will be passed explicitly


async def _get_pull_token(storage: ImageStorage, repo: str, client: httpx.AsyncClient) -> PullToken:
    if token := storage.get_pull_token(registry='docker.io', repo=repo):
        return token

    resp = await client.get(
        'https://auth.docker.io/token?service=registry.docker.io&'
        f'scope=repository:{repo}:pull',
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status() # Raise an exception for HTTP errors
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


async def _find_image_digest(
    repo: str,
    tag: str,
    token: PullToken,
    client: httpx.AsyncClient,
    architecture: str = 'amd64',
) -> tuple[Digest, MediaType]:
    index_response = await client.get(
        f'{REGISTRY_BASE}/v2/{repo}/manifests/{tag}',
        headers={
            'Accept': ','.join([
                'application/vnd.docker.distribution.manifest.list.v2+json',
                'application/vnd.oci.image.index.v1+json',
            ]),
            'Authorization': f'Bearer {token}',
        },
        timeout=REQUEST_TIMEOUT,
    )
    index_response.raise_for_status() # Raise an exception for HTTP errors
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

    return Digest(manifest_spec['digest']), MediaType(manifest_spec['mediaType'])


async def _get_image_manifest(
    storage: ImageStorage,
    repo: str,
    reference: str,
    client: httpx.AsyncClient,
    token: PullToken | None = None,
) -> Manifest:
    if token is None:
        raise TokenRequiredError('token is required to fetch manifest')

    if reference.startswith('sha256:'):
        digest = Digest(reference)
        mediatype = None
        tags = None
    else:
        digest, mediatype = await _find_image_digest(repo, reference, token, client)
        tags = [reference]

    if mediatype is None:
        raise RuntimeError('need mediatype to fetch manifest')
    if digest is None:
        raise RuntimeError('need digest to fetch manifest')

    manifest_response = await client.get(
        url=f'{REGISTRY_BASE}/v2/{repo}/manifests/{digest}',
        headers={
            'Accept': mediatype,
            'Authorization': f'Bearer {token}',
        },
        timeout=REQUEST_TIMEOUT,
    )
    manifest_response.raise_for_status()
    manifest_data = manifest_response.json()
    manifest = Manifest(
        registry='docker.io',
        name=repo,
        digest=digest,
        config=(
            Digest(manifest_data['config']['digest']),
            MediaType(manifest_data['config']['mediaType']),
        ),
        layers=[
            (Digest(layer['digest']), MediaType(layer['mediaType']))
            for layer in manifest_data['layers']
        ],
    )
    storage.store_manifest(manifest=manifest, tags=tags)
    return manifest


async def _get_image_layers(
    storage: ImageStorage,
    manifest: Manifest,
    client: httpx.AsyncClient,
    token: PullToken | None = None,
) -> list[ImageLayer]:
    layers = []
    for layer_digest, layer_mediatype in manifest.layers:
        if token is None:
            raise TokenRequiredError('token is required to fetch layers')

        layer_response = await client.get(
            f'{REGISTRY_BASE}/v2/{manifest.name}/blobs/{layer_digest}',
            headers={
                'Accept': layer_mediatype,
                'Authorization': f'Bearer {token}',
            },
            timeout=REQUEST_TIMEOUT,
        )
        layer_response.raise_for_status() # Raise an exception for HTTP errors
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


def _find_ids(source_path: pathlib.Path) -> list[str]:
    """Extract IDs from /etc/passwd or /etc/group files"""
    ids = []
    try:
        with source_path.open() as source_file:
            for line in source_file:
                parts = line.split(':')
                if len(parts) >= 3:
                    ids.append(parts[2])
    except IOError:
        pass
    return ids


def _discover_image_ids(layers: list[ImageLayer]) -> tuple[list[str], list[str]]:
    """Discover UIDs and GIDs from image layers"""
    uids = []
    gids = []

    # Search through layers in reverse order (top layer first)
    for layer in reversed(layers):
        passwd_path = layer.path / 'etc' / 'passwd'
        group_path = layer.path / 'etc' / 'group'

        # If we haven't found UIDs yet and this layer has /etc/passwd, use it
        if not uids and passwd_path.exists():
            uids = _find_ids(passwd_path)

        # If we haven't found GIDs yet and this layer has /etc/group, use it
        if not gids and group_path.exists():
            gids = _find_ids(group_path)

        # If we found both, we can stop searching
        if uids and gids:
            break

    return uids, gids


async def _get_image_config(
    storage: ImageStorage,
    manifest: Manifest,
    client: httpx.AsyncClient,
    token: PullToken | None,
) -> ImageConfig:
    if token is None:
        raise TokenRequiredError('token is required to fetch config')
    config_resp = await client.get(
        f'{REGISTRY_BASE}/v2/{manifest.name}/blobs/{manifest.config[0]}',
        headers={
            'Accept': manifest.config[1],
            'Authorization': f'Bearer {token}',
        },
        timeout=REQUEST_TIMEOUT,
    )
    config_resp.raise_for_status() # Raise an exception for HTTP errors

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


async def load_docker_image(storage: ImageStorage, image_name: str) -> Image:
    """Fetch image from the docker.io registry"""
    repo, _, reference = image_name.partition(':')
    reference = reference or 'latest'

    async with httpx.AsyncClient(follow_redirects=True) as client:
        token = await _get_pull_token(storage, repo, client)

        manifest = await _get_image_manifest(storage, repo, reference, client, token)
        image_config = await _get_image_config(storage, manifest, client, token)
        layers = await _get_image_layers(storage, manifest, client, token)

        # Discover UIDs and GIDs from the layers and update the image config
        uids, gids = _discover_image_ids(layers)
        if uids or gids:
            # Update the config with discovered IDs
            image_config.uids = uids
            image_config.gids = gids
            # Store the updated config
            storage.store_image_config(manifest, image_config)

        return Image(
            registry='docker.io',
            manifest=manifest,
            config=image_config,
            layers=layers,
        )

