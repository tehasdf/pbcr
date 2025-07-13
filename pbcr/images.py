"""Images-related subcommands
"""

from pbcr.docker_registry import load_docker_image
from pbcr.types import ImageStorage, ImageSummary


def _format_images_table(images: list[ImageSummary]) -> str:
    """Format a list of images into a nice table"""
    if not images:
        return "No images found."

    # Define headers and calculate column widths
    headers = ["REPOSITORY", "REGISTRY", "DIGEST"]
    # Extract data for each image
    rows = []
    for image in images:
        # Truncate digest to first 12 characters for readability
        short_digest = str(image.digest).replace('sha256:', '')[:12]

        rows.append([
            image.name,
            image.registry,
            short_digest,
        ])
    # Calculate column widths
    col_widths = [len(header) for header in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # Add padding
    col_widths = [w + 2 for w in col_widths]

    # Build the table
    lines = []

    # Header row
    header_line = "".join(headers[i].ljust(col_widths[i]) for i in range(len(headers)))
    lines.append(header_line.rstrip())

    # Data rows
    for row in rows:
        data_line = "".join(row[i].ljust(col_widths[i]) for i in range(len(row)))
        lines.append(data_line.rstrip())
    return "\n".join(lines)


def list_images_command(storage: ImageStorage):
    """Display images in the storage"""
    images = storage.list_images()
    print(_format_images_table(images))


async def pull_image(storage: ImageStorage, image_name: str):
    """Fetch an image into the storage"""
    if image_name.startswith('docker.io/'):
        image_name = image_name.replace('docker.io/', '', 1)
        img = await load_docker_image(storage, image_name)
    else:
        raise ValueError(f'unknown image reference: {image_name}')
    print(f'Fetched image {img.manifest.name} with {len(img.layers)} layers')


async def pull_image_command(storage: ImageStorage, image_names: list[str]):
    """A CLI command facade for pull_image"""
    for image_name in image_names:
        await pull_image(storage, image_name)
