import json

from pbcr.types import Storage


def list_images_command(storage: Storage, **kwargs):
    images = storage.list_images()
    print(json.dumps(images, indent=4))
