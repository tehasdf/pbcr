import json
from datetime import datetime

import requests

from pbcr.types import Storage, PullToken

REGISTRY_BASE = 'https://registry-1.docker.io'


def _get_pull_token(repo: str) -> PullToken:
    resp = requests.get(
        'https://auth.docker.io/token?service=registry.docker.io&'
        f'scope=repository:{repo}:pull',
    )
    token_data = resp.json()
    token_data['issued_at'] = token_data['issued_at'][:-4]
    return PullToken.fromdict(token_data)


def _get_image_manifest(
    storage: Storage,
    repo: str,
    tag: str,
    token: str,
    architecture: str='amd64'
):
    url = f'{REGISTRY_BASE}/v2/{repo}/manifests/{tag}'
    resp = requests.get(
        url,
        headers={
            'Accept': 'application/vnd.oci.image.index.v1+json',
            # 'Accept': 'application/vnd.oci.image.manifest.v1+json',
            'Authorization': f'Bearer {token}',
        }
    )
    try:
        return resp.json()
    except ValueError:
        raise ValueError(f'unexpected response from {url}: {resp.content!r}')


def pull_image_from_docker(storage: Storage, image_name: str):
    repo, _, reference = image_name.partition(':')
    reference = reference or 'latest'
    token = storage.get_pull_token(registry='docker.io', repo=repo)
    if not token:
        token = _get_pull_token(repo)
        storage.store_pull_token(registry='docker.io', repo=repo, token=token)

    manifest = _get_image_manifest(storage, repo, reference, token.token)
    print('manifest', json.dumps(manifest, indent=4))
