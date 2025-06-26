"""Test table formatting for images"""

from pbcr.types import Manifest, Digest
from pbcr.images import _format_images_table


def test_format_images_table_empty():
    """Test formatting empty images list"""
    result = _format_images_table([])
    assert result == "No images found."


def test_format_images_table_single():
    """Test formatting single image"""
    manifest = Manifest(
        registry="docker.io",
        name="library/hello-world",
        digest=Digest("sha256:abcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"),
        config=(Digest("sha256:config123"), "application/vnd.docker.image.manifest.v2+json"),
        layers=[
            (Digest("sha256:layer1"), "application/vnd.docker.image.rootfs.diff.tar.gzip"),
            (Digest("sha256:layer2"), "application/vnd.docker.image.rootfs.diff.tar.gzip"),
        ]
    )
    
    result = _format_images_table([manifest])
    lines = result.split('\n')
    
    # Check that we have header and data rows
    assert len(lines) == 2
    assert "REPOSITORY" in lines[0]
    assert "REGISTRY" in lines[0]
    assert "DIGEST" in lines[0]
    assert "LAYERS" in lines[0]
    
    # Check data row
    assert "library/hello-world" in lines[1]
    assert "docker.io" in lines[1]
    assert "abcd12345678" in lines[1]  # First 12 chars of digest
    assert "2" in lines[1]  # Number of layers


def test_format_images_table_multiple():
    """Test formatting multiple images"""
    manifests = [
        Manifest(
            registry="docker.io",
            name="library/hello-world",
            digest=Digest("sha256:abcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab"),
            config=(Digest("sha256:config123"), "application/vnd.docker.image.manifest.v2+json"),
            layers=[
                (Digest("sha256:layer1"), "application/vnd.docker.image.rootfs.diff.tar.gzip"),
            ]
        ),
        Manifest(
            registry="quay.io",
            name="prometheus/prometheus",
            digest=Digest("sha256:efgh5678901234567890efgh5678901234567890efgh5678901234567890efgh"),
            config=(Digest("sha256:config456"), "application/vnd.docker.image.manifest.v2+json"),
            layers=[
                (Digest("sha256:layer2"), "application/vnd.docker.image.rootfs.diff.tar.gzip"),
                (Digest("sha256:layer3"), "application/vnd.docker.image.rootfs.diff.tar.gzip"),
                (Digest("sha256:layer4"), "application/vnd.docker.image.rootfs.diff.tar.gzip"),
            ]
        )
    ]
    
    result = _format_images_table(manifests)
    lines = result.split('\n')
    
    # Check that we have header + 2 data rows
    assert len(lines) == 3
    
    # Check header
    assert "REPOSITORY" in lines[0]
    assert "REGISTRY" in lines[0] 
    assert "DIGEST" in lines[0]
    assert "LAYERS" in lines[0]
    
    # Check first data row
    assert "library/hello-world" in lines[1]
    assert "docker.io" in lines[1]
    assert "abcd12345678" in lines[1]
    assert "1" in lines[1]
    
    # Check second data row
    assert "prometheus/prometheus" in lines[2]
    assert "quay.io" in lines[2]
    assert "efgh56789012" in lines[2]
    assert "3" in lines[2]