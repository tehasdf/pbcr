"""Test table formatting for images"""

from pbcr.types import ImageSummary, Digest
from pbcr.images import _format_images_table


def test_format_images_table_empty():
    """Test formatting empty images list"""
    result = _format_images_table([])
    assert result == "No images found."


def test_format_images_table_single():
    """Test formatting single image"""
    summary = ImageSummary(
        registry="registry1.com",
        name="foo",
        digest=Digest("sha256:abc123def456789012345678901234567890123456789012345678901234567890"),
        tags=["latest"]
    )

    result = _format_images_table([summary])
    lines = result.split('\n')
    # Check that we have header and data rows
    assert len(lines) == 2
    assert "REPOSITORY" in lines[0]
    assert "REGISTRY" in lines[0]
    assert "DIGEST" in lines[0]
    assert "LAYERS" not in lines[0] # LAYERS column should not be present

    # Check data row
    assert "foo" in lines[1]
    assert "registry1.com" in lines[1]
    assert "abc123def456" in lines[1]  # First 12 chars of digest


def test_format_images_table_multiple():
    """Test formatting multiple images"""
    summaries = [
        ImageSummary(
            registry="registry1.com",
            name="foo",
            digest=Digest(
                "sha256:abc123def456789012345678901234567890123456789012345678901234567890"
            ),
            tags=["v1.0"]
        ),
        ImageSummary(
            registry="registry2.com",
            name="bar",
            digest=Digest(
                "sha256:def456ghi789012345678901234567890123456789012345678901234567890def"
            ),
            tags=["latest", "v2.0"]
        )
    ]

    result = _format_images_table(summaries)
    lines = result.split('\n')

    # Check that we have header + 2 data rows
    assert len(lines) == 3

    # Check header
    assert "REPOSITORY" in lines[0]
    assert "REGISTRY" in lines[0]
    assert "DIGEST" in lines[0]
    assert "LAYERS" not in lines[0] # LAYERS column should not be present

    # Check first data row
    assert "foo" in lines[1]
    assert "registry1.com" in lines[1]
    assert "abc123def456" in lines[1]

    # Check second data row
    assert "bar" in lines[2]
    assert "registry2.com" in lines[2]
    assert "def456ghi789" in lines[2]
