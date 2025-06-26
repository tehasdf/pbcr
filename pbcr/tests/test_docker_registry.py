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

    def get_manifest(self, registry, repo):
        """Mock get_manifest."""
        return self.manifests.get((registry, repo))

    def store_manifest(self, manifest):
        """Mock store_manifest."""
        self.manifests[(manifest.registry, manifest.name)] = manifest

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


def test_get_pull_token_cached(mock_storage, mock_token):
    """Test retrieving a cached pull token."""
    mock_storage.store_pull_token("docker.io", "library/ubuntu", mock_token)

    token = _get_pull_token(mock_storage, "library/ubuntu")

    assert token == mock_token


@mock.patch("requests.get")
def test_get_pull_token_fetch(mock_get_request, mock_storage):
    """Test fetching a pull token from the registry."""
    mock_response = mock.Mock()
    mock_response.json.return_value = {
        "token": "new_token",
        "expires_in": 300,
        "issued_at": "2023-01-01T00:00:00.0000",
    }
    mock_get_request.return_value = mock_response

    token = _get_pull_token(mock_storage, "library/ubuntu")

    assert token.token == "new_token"
    assert mock_get_request.called
    assert mock_storage.get_pull_token("docker.io", "library/ubuntu") == token


@mock.patch("requests.get")
def test_find_image_digest(mock_get_request, mock_token):
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
    mock_get_request.return_value = mock_response

    digest, mediatype = _find_image_digest("library/ubuntu", "latest", mock_token)

    assert digest == "sha256:amd64digest"
    assert mediatype == "application/vnd.docker.distribution.manifest.v2+json"
    mock_get_request.assert_called_once()


@mock.patch("requests.get")
def test_find_image_digest_not_found(mock_get_request, mock_token):
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
    mock_get_request.return_value = mock_response

    with pytest.raises(ValueError, match="manifest for amd64 not found"):
        _find_image_digest("library/ubuntu", "latest", mock_token)


def test_get_image_manifest_cached(mock_storage, mock_manifest):
    """Test retrieving a cached image manifest."""
    mock_storage.store_manifest(mock_manifest)

    manifest = _get_image_manifest(mock_storage, "library/ubuntu")

    assert manifest == mock_manifest


@mock.patch("requests.get")
def test_get_image_manifest_fetch(mock_get_request, mock_storage, mock_token):
    """Test fetching an image manifest from the registry."""
    mock_response = mock.Mock()
    mock_response.json.return_value = {
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
    mock_get_request.return_value = mock_response

    manifest = _get_image_manifest(
        mock_storage,
        "library/ubuntu",
        Digest("sha256:abc123"),
        MediaType("application/vnd.docker.distribution.manifest.v2+json"),
        mock_token
    )

    assert manifest.registry == "docker.io"
    assert manifest.name == "library/ubuntu"
    assert manifest.digest == "sha256:abc123"
    assert manifest.config[0] == "sha256:config123"
    assert len(manifest.layers) == 2
    assert mock_storage.get_manifest("docker.io", "library/ubuntu") == manifest


def test_get_image_config_cached(mock_storage, mock_manifest, mock_config):
    """Test retrieving a cached image config."""
    mock_storage.store_image_config(mock_manifest, mock_config)

    config = _get_image_config(mock_storage, mock_manifest, None)

    assert config == mock_config


@mock.patch("requests.get")
def test_get_image_config_fetch(mock_get_request, mock_storage,
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
    mock_get_request.return_value = mock_response

    config = _get_image_config(mock_storage, mock_manifest, mock_token)

    assert config.architecture == "amd64"
    assert config.os == "linux"
    assert config.config["Cmd"] == ["/bin/bash"]
    assert mock_storage.get_image_config(mock_manifest) == config


@mock.patch("requests.get")
def test_get_image_layers(mock_get_request, mock_storage,
                          mock_manifest, mock_token):
    """Test fetching image layers from the registry."""
    mock_response = mock.Mock()
    mock_response.content = b"layer_data"
    mock_get_request.return_value = mock_response

    layers = _get_image_layers(mock_storage, mock_manifest, mock_token)

    assert len(layers) == 2
    assert layers[0].digest == "sha256:layer1"
    assert layers[1].digest == "sha256:layer2"
    assert mock_get_request.call_count == 2


@mock.patch("pbcr.docker_registry._get_pull_token")
@mock.patch("pbcr.docker_registry._find_image_digest")
@mock.patch("pbcr.docker_registry._get_image_manifest")
@mock.patch("pbcr.docker_registry._get_image_config")
@mock.patch("pbcr.docker_registry._get_image_layers")
def test_pull_image_from_docker(
    mock_get_layers, mock_get_config, mock_get_manifest, mock_find_digest,
    mock_get_token, mock_storage, mock_manifest, mock_config
):
    # pylint: disable=too-many-arguments, unused-argument
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

    image = pull_image_from_docker(mock_storage, "ubuntu:latest")

    assert image.registry == "docker.io"
    assert image.manifest == mock_manifest
    assert image.config == mock_config
    assert len(image.layers) == 2


@mock.patch("pbcr.docker_registry._get_image_manifest")
@mock.patch("pbcr.docker_registry._get_image_config")
@mock.patch("pbcr.docker_registry._get_image_layers")
def test_load_docker_image(
    mock_get_layers, mock_get_config, mock_get_manifest,
    mock_storage, mock_manifest, mock_config
):
    # pylint: disable=too-many-arguments, unused-argument
    """Test the load_docker_image function."""
    mock_get_manifest.return_value = mock_manifest
    mock_get_config.return_value = mock_config
    mock_get_layers.return_value = [
        ImageLayer(digest=Digest("sha256:layer1"), path=pathlib.Path("/tmp/layer1")),
        ImageLayer(digest=Digest("sha256:layer2"), path=pathlib.Path("/tmp/layer2"))
    ]

    image = load_docker_image(mock_storage, "ubuntu:latest")

    assert image.registry == "docker.io"
    assert image.manifest == mock_manifest
    assert image.config == mock_config
    assert len(image.layers) == 2
