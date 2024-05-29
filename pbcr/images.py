"""Images-related subcommands
"""

from pbcr.docker_registry import pull_image_from_docker
from pbcr.types import ImageStorage


def list_images_command(storage: ImageStorage):
    """Display images in the storage"""
    images = storage.list_images()
    for image in images:
        print(image)


def pull_image(storage: ImageStorage, image_name: str):
    """Fetch an image into the storage"""
    if image_name.startswith('docker.io/'):
        image_name = image_name.replace('docker.io/', '', 1)
        img = pull_image_from_docker(storage, image_name)
    else:
        raise ValueError(f'unknown image reference: {image_name}')
    print(f'Fetched image {img.manifest.name} with {len(img.layers)} layers')


def pull_image_command(storage: ImageStorage, image_names: list[str]):
    """A CLI command facade for pull_image"""
    for image_name in image_names:
        pull_image(storage, image_name)
