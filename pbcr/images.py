import json

from pbcr.docker_registry import pull_image_from_docker
from pbcr.types import Storage


def list_images_command(storage: Storage, **kwargs):
    images = storage.list_images()
    print(json.dumps(images, indent=4))


def pull_image(storage: Storage, image_name: str):
    if image_name.startswith('docker.io/'):
        image_name = image_name.replace('docker.io/', '', 1)
        img = pull_image_from_docker(storage, image_name)
    else:
        raise ValueError(f'unknown image reference: {image_name}')
    print(f'Fetched image {img.manifest.name} with {len(img.layers)} layers')


def pull_image_command(storage: Storage, image_names: list[str], **kwargs):
    for image_name in image_names:
        pull_image(storage, image_name)
