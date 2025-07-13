"""Tests for docker_registry.py module"""

# disable redefined-outer-name, because this is usually the case
# with pytest fixtures declared in the same module
# pylint: disable=redefined-outer-name

import pathlib
from unittest import mock

import pytest
import httpx

from pbcr.docker_registry import (
    _get_pull_token,
    _find_image_digest,
    _get_image_manifest,
    _get_image_layers,
    _get_image_config,
    load_docker_image,
)
from pbcr.types import (
    PullToken,
    Manifest,
    Digest,
    MediaType,
    ImageConfig,
    ImageLayer,
)


class MockImageStorage:
    """Mock storage for image related operations."""
    def __init__(self):
        self.tokens = {}
        self.manifests = {}
        self.configs = {}
        self.layers = {}

    def get_pull_token(self, registry, repo):
        """Mock get_pull_token."""
        return self.tokens.get((registry, repo))

    def store_pull_token(self, registry, repo, token):
        """Mock store_pull_token."""
        self.tokens[(registry, repo)] = token

    def get_manifest(self, registry, repo, reference=None):
        """Mock get_manifest."""
        return self.manifests.get((registry, repo, reference))

    def store_manifest(self, manifest, tags=None):
        """Mock store_manifest."""
        if tags:
            tag = tags[0]
        else:
            tag = None
        self.manifests[(manifest.registry, manifest.name, tag)] = manifest

    def get_image_config(self, manifest):
        """Mock get_image_config."""
        return self.configs.get((manifest.registry, manifest.name))

    def store_image_config(self, manifest, config):
        """Mock store_image_config."""
        self.configs[(manifest.registry, manifest.name)] = config

    def get_image_layer(self, manifest, digest):
        """Mock get_image_layer."""
        return self.layers.get((manifest.registry, manifest.name, digest))

    def store_image_layer(self, manifest, digest, data):
        """Mock store_image_layer."""
        _ = data  # Unused data
        path = pathlib.Path(f"/tmp/{digest}")
        self.layers[(manifest.registry, manifest.name, digest)] = ImageLayer(
            digest=digest,
            path=path,
        )
        return path


@pytest.fixture
def mock_storage():
    """Fixture for a mock image storage."""
    return MockImageStorage()


@pytest.fixture
def mock_token():
    """Fixture for a mock pull token."""
    return PullToken(
        token="mock_token",
        expires_in=300,
        issued_at="2023-01-01T00:00:00",
    )


@pytest.fixture
def mock_manifest():
    """Fixture for a mock image manifest."""
    return Manifest(
        registry="docker.io",
        name="library/ubuntu",
        digest=Digest("sha256:abc123"),
        config=(Digest("sha256:config123"),
                MediaType("application/vnd.docker.container.image.v1+json")),
        layers=[
            (Digest("sha256:layer1"),
             MediaType("application/vnd.docker.image.rootfs.diff.tar.gzip")),
            (Digest("sha256:layer2"),
             MediaType("application/vnd.docker.image.rootfs.diff.tar.gzip")),
        ],
    )


@pytest.fixture
def mock_config():
    """Fixture for a mock image config."""
    return ImageConfig(
        architecture="amd64",
        os="linux",
        config={
            "Cmd": ["/bin/bash"],
            "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"],
        },
    )


@pytest.mark.asyncio
async def test_get_pull_token_cached(mock_storage, mock_token):
    """Test retrieving a cached pull token."""
    mock_storage.store_pull_token("docker.io", "library/ubuntu", mock_token)
    client = httpx.AsyncClient() # Dummy client, not used in this test path

    token = await _get_pull_token(mock_storage, "library/ubuntu", client)

    assert token == mock_token


@pytest.mark.asyncio
async def test_get_pull_token_fetch(mock_storage):
    """Test fetching a pull token from the registry."""
    response_data = {
        "token": "new_token",
        "expires_in": 300,
        "issued_at": "2023-01-01T00:00:00.0000",
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_data)
        )
    )

    token = await _get_pull_token(mock_storage, "library/ubuntu", client)
    assert token.token == "new_token"
    assert mock_storage.get_pull_token("docker.io", "library/ubuntu") == token


@pytest.mark.asyncio
async def test_find_image_digest(mock_token):
    """Test finding the image digest for a specific architecture."""
    response_data = {
        "manifests": [
            {
                "digest": "sha256:arm64digest",
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "platform": {"architecture": "arm64"}
            },
            {
                "digest": "sha256:amd64digest",
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "platform": {"architecture": "amd64"}
            }
        ]
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_data)
        )
    )

    digest, mediatype = await _find_image_digest("library/ubuntu", "latest", mock_token, client)

    assert digest == "sha256:amd64digest"
    assert mediatype == "application/vnd.docker.distribution.manifest.v2+json"


@pytest.mark.asyncio
async def test_find_image_digest_not_found(mock_token):
    """Test case where the image digest for the architecture is not found."""
    response_data = {
        "manifests": [
            {
                "digest": "sha256:arm64digest",
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "platform": {"architecture": "arm64"}
            }
        ]
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_data)
        )
    )

    with pytest.raises(ValueError, match="manifest for amd64 not found"):
        await _find_image_digest("library/ubuntu", "latest", mock_token, client)


@pytest.mark.asyncio
async def test_get_image_manifest_fetch(mock_storage, mock_token):
    """Test fetching an image manifest from the registry."""
    manifest_list_response_data = {
        "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
        "manifests": [
            {
                "digest": "sha256:abc123",
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "platform": {"architecture": "amd64"}
            }
        ]
    }

    manifest_response_data = {
        "config": {
            "digest": "sha256:config123",
            "mediaType": "application/vnd.docker.container.image.v1+json"
        },
        "layers": [
            {
                "digest": "sha256:layer1",
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip"
            },
            {
                "digest": "sha256:layer2",
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip"
            }
        ]
    }

    def mock_transport(request):
        if "manifests/latest" in request.url.path:
            return httpx.Response(200, json=manifest_list_response_data)
        if "manifests/sha256:abc123" in request.url.path:
            return httpx.Response(200, json=manifest_response_data)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_transport))

    manifest = await _get_image_manifest(
        mock_storage,
        "library/ubuntu",
        "latest",
        client,
        mock_token
    )

    assert manifest.registry == "docker.io"
    assert manifest.name == "library/ubuntu"
    assert manifest.digest == "sha256:abc123"
    assert manifest.config[0] == "sha256:config123"
    assert len(manifest.layers) == 2
    assert mock_storage.get_manifest("docker.io", "library/ubuntu", "latest") == manifest


@pytest.mark.asyncio
async def test_get_image_config_fetch(mock_storage, mock_manifest, mock_token):
    """Test fetching an image config from the registry."""
    response_data = {
        "architecture": "amd64",
        "os": "linux",
        "config": {
            "Cmd": ["/bin/bash"],
            "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
        }
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_data)
        )
    )

    config = await _get_image_config(mock_storage, mock_manifest, client, mock_token)

    assert config.architecture == "amd64"
    assert config.os == "linux"
    assert config.config["Cmd"] == ["/bin/bash"]
    assert mock_storage.get_image_config(mock_manifest) == config


@pytest.mark.asyncio
async def test_get_image_layers(mock_storage, mock_manifest, mock_token):
    """Test fetching image layers from the registry."""
    layer_data = b"layer_data"
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=layer_data)
        )
    )

    layers = await _get_image_layers(mock_storage, mock_manifest, client, mock_token)

    assert len(layers) == 2
    assert layers[0].digest == "sha256:layer1"
    assert layers[1].digest == "sha256:layer2"


@pytest.mark.asyncio
async def test_load_docker_image(mock_storage, mock_manifest, mock_config):
    # pylint: disable=too-many-arguments, too-many-positional-arguments, unused-argument
    """Test the main load_docker_image function."""
    token_response_data = {
        "token": "test_token",
        "expires_in": 300,
        "issued_at": "2023-01-01T00:00:00"
    }
    manifest_list_response_data = {
        "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
        "manifests": [
            {
                "digest": "sha256:digest",
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "platform": {"architecture": "amd64"}
            }
        ]
    }
    manifest_response_data = {
        "config": {
            "digest": "sha256:config123",
            "mediaType": "application/vnd.docker.container.image.v1+json"
        },
        "layers": [
            {
                "digest": "sha256:layer1",
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip"
            },
            {
                "digest": "sha256:layer2",
                "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip"
            }
        ]
    }
    config_response_data = {
        "architecture": "amd64",
        "os": "linux",
        "config": {
            "Cmd": ["/bin/bash"],
            "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
        }
    }
    layer_data = b"layer_data"

    def mock_transport(request):
        if "auth.docker.io" in request.url.host:
            return httpx.Response(200, json=token_response_data)
        if "manifests/latest" in request.url.path:
            return httpx.Response(200, json=manifest_list_response_data)
        if "manifests/sha256:digest" in request.url.path:
            return httpx.Response(200, json=manifest_response_data)
        if "blobs/sha256:config123" in request.url.path:
            return httpx.Response(200, json=config_response_data)
        if "blobs/sha256:layer1" in request.url.path or "blobs/sha256:layer2" in request.url.path:
            return httpx.Response(200, content=layer_data)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_transport))

    # Patch the internal client creation in load_docker_image
    with mock.patch('httpx.AsyncClient', return_value=client):
        image = await load_docker_image(mock_storage, "ubuntu:latest")

    assert image.registry == "docker.io"
    assert image.manifest.digest == "sha256:digest"
    assert image.config.architecture == "amd64"
    assert len(image.layers) == 2
