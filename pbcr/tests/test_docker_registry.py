"""Tests for docker_registry.py module"""

# disable redefined-outer-name, because this is usually the case
# with pytest fixtures declared in the same module
# pylint: disable=redefined-outer-name

import pathlib
from unittest import mock

import pytest

from pbcr.docker_registry import (
    _get_pull_token,
    _find_image_digest,
    _get_image_manifest,
    _get_image_layers,
    _get_image_config,
    pull_image_from_docker,
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

    token = await _get_pull_token(mock_storage, "library/ubuntu")

    assert token == mock_token


@pytest.mark.asyncio
@mock.patch("httpx.AsyncClient")
async def test_get_pull_token_fetch(mock_async_client, mock_storage):
    """Test fetching a pull token from the registry."""
    mock_response = mock.Mock()
    mock_response.json.return_value = {
        "token": "new_token",
        "expires_in": 300,
        "issued_at": "2023-01-01T00:00:00.0000",
    }
    mock_async_client.return_value.__aenter__.return_value.get.return_value = mock_response

    token = await _get_pull_token(mock_storage, "library/ubuntu")

    assert token.token == "new_token"
    mock_async_client.return_value.__aenter__.return_value.get.assert_called_once()
    assert mock_storage.get_pull_token("docker.io", "library/ubuntu") == token


@pytest.mark.asyncio
@mock.patch("httpx.AsyncClient")
async def test_find_image_digest(mock_async_client, mock_token):
    """Test finding the image digest for a specific architecture."""
    mock_response = mock.Mock()
    mock_response.json.return_value = {
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
    mock_async_client.return_value.__aenter__.return_value.get.return_value = mock_response

    digest, mediatype = await _find_image_digest("library/ubuntu", "latest", mock_token)

    assert digest == "sha256:amd64digest"
    assert mediatype == "application/vnd.docker.distribution.manifest.v2+json"
    mock_async_client.return_value.__aenter__.return_value.get.assert_called_once()


@pytest.mark.asyncio
@mock.patch("httpx.AsyncClient")
async def test_find_image_digest_not_found(mock_async_client, mock_token):
    """Test case where the image digest for the architecture is not found."""
    mock_response = mock.Mock()
    mock_response.json.return_value = {
        "manifests": [
            {
                "digest": "sha256:arm64digest",
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "platform": {"architecture": "arm64"}
            }
        ]
    }
    mock_async_client.return_value.__aenter__.return_value.get.return_value = mock_response

    with pytest.raises(ValueError, match="manifest for amd64 not found"):
        await _find_image_digest("library/ubuntu", "latest", mock_token)


@pytest.mark.asyncio
async def test_get_image_manifest_cached(mock_storage, mock_manifest):
    """Test retrieving a cached image manifest."""
    mock_storage.store_manifest(mock_manifest, tags=["latest"])

    manifest = await _get_image_manifest(mock_storage, "library/ubuntu", "latest")

    assert manifest == mock_manifest


@pytest.mark.asyncio
@mock.patch("httpx.AsyncClient")
async def test_get_image_manifest_fetch(mock_async_client, mock_storage, mock_token):
    """Test fetching an image manifest from the registry."""
    mock_response_manifest_list = mock.Mock()
    mock_response_manifest_list.json.return_value = {
        "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
        "manifests": [
            {
                "digest": "sha256:abc123",
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "platform": {"architecture": "amd64"}
            }
        ]
    }

    mock_response_manifest = mock.Mock()
    mock_response_manifest.json.return_value = {
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

    mock_async_client.return_value.__aenter__.return_value.get.side_effect = [
        mock_response_manifest_list,
        mock_response_manifest
    ]

    manifest = await _get_image_manifest(
        mock_storage,
        "library/ubuntu",
        "latest",
        mock_token
    )

    assert manifest.registry == "docker.io"
    assert manifest.name == "library/ubuntu"
    assert manifest.digest == "sha256:abc123"
    assert manifest.config[0] == "sha256:config123"
    assert len(manifest.layers) == 2
    assert mock_storage.get_manifest("docker.io", "library/ubuntu", "latest") == manifest
    assert mock_async_client.return_value.__aenter__.return_value.get.call_count == 2


@pytest.mark.asyncio
async def test_get_image_config_cached(mock_storage, mock_manifest, mock_config):
    """Test retrieving a cached image config."""
    mock_storage.store_image_config(mock_manifest, mock_config)

    config = await _get_image_config(mock_storage, mock_manifest, None)

    assert config == mock_config


@pytest.mark.asyncio
@mock.patch("httpx.AsyncClient")
async def test_get_image_config_fetch(mock_async_client, mock_storage,
                                 mock_manifest, mock_token):
    """Test fetching an image config from the registry."""
    mock_response = mock.Mock()
    mock_response.json.return_value = {
        "architecture": "amd64",
        "os": "linux",
        "config": {
            "Cmd": ["/bin/bash"],
            "Env": ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
        }
    }
    mock_async_client.return_value.__aenter__.return_value.get.return_value = mock_response

    config = await _get_image_config(mock_storage, mock_manifest, mock_token)

    assert config.architecture == "amd64"
    assert config.os == "linux"
    assert config.config["Cmd"] == ["/bin/bash"]
    assert mock_storage.get_image_config(mock_manifest) == config
    mock_async_client.return_value.__aenter__.return_value.get.assert_called_once()


@pytest.mark.asyncio
@mock.patch("httpx.AsyncClient")
async def test_get_image_layers(mock_async_client, mock_storage,
                          mock_manifest, mock_token):
    """Test fetching image layers from the registry."""
    mock_response = mock.Mock()
    mock_response.content = b"layer_data"
    mock_async_client.return_value.__aenter__.return_value.get.return_value = mock_response

    layers = await _get_image_layers(mock_storage, mock_manifest, mock_token)

    assert len(layers) == 2
    assert layers[0].digest == "sha256:layer1"
    assert layers[1].digest == "sha256:layer2"
    assert mock_async_client.return_value.__aenter__.return_value.get.call_count == 2


@pytest.mark.asyncio
@mock.patch("pbcr.docker_registry._get_pull_token")
@mock.patch("pbcr.docker_registry._find_image_digest")
@mock.patch("pbcr.docker_registry._get_image_manifest")
@mock.patch("pbcr.docker_registry._get_image_config")
@mock.patch("pbcr.docker_registry._get_image_layers")
async def test_pull_image_from_docker(
    mock_get_layers, mock_get_config, mock_get_manifest, mock_find_digest,
    mock_get_token, mock_storage, mock_manifest, mock_config
):
    # pylint: disable=too-many-arguments, too-many-positional-arguments, unused-argument
    """Test the main pull_image_from_docker function."""
    mock_get_token.return_value = PullToken(
        token="test_token",
        expires_in=300,
        issued_at="2023-01-01T00:00:00"
    )
    mock_find_digest.return_value = (Digest("sha256:digest"), MediaType("application/type"))
    mock_get_manifest.return_value = mock_manifest
    mock_get_config.return_value = mock_config
    mock_get_layers.return_value = [
        ImageLayer(digest=Digest("sha256:layer1"), path=pathlib.Path("/tmp/layer1")),
        ImageLayer(digest=Digest("sha256:layer2"), path=pathlib.Path("/tmp/layer2"))
    ]

    image = await pull_image_from_docker(mock_storage, "ubuntu:latest")

    assert image.registry == "docker.io"
    assert image.manifest == mock_manifest
    assert image.config == mock_config
    assert len(image.layers) == 2


@pytest.mark.asyncio
@mock.patch("pbcr.docker_registry._get_image_manifest")
@mock.patch("pbcr.docker_registry._get_image_config")
@mock.patch("pbcr.docker_registry._get_image_layers")
async def test_load_docker_image(
    mock_get_layers, mock_get_config, mock_get_manifest,
    mock_storage, mock_manifest, mock_config
):
    # pylint: disable=too-many-arguments, too-many-positional-arguments, unused-argument
    """Test the load_docker_image function."""
    mock_get_manifest.return_value = mock_manifest
    mock_get_config.return_value = mock_config
    mock_get_layers.return_value = [
        ImageLayer(digest=Digest("sha256:layer1"), path=pathlib.Path("/tmp/layer1")),
        ImageLayer(digest=Digest("sha256:layer2"), path=pathlib.Path("/tmp/layer2"))
    ]

    image = await load_docker_image(mock_storage, "ubuntu:latest")

    assert image.registry == "docker.io"
    assert image.manifest == mock_manifest
    assert image.config == mock_config
    assert len(image.layers) == 2
