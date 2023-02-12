import argparse

from pbcr.images import list_images_command, pull_image_command
from pbcr.storage import make_storage


def main():
    parser = argparse.ArgumentParser(
        prog='pbcr',
    )
    subparsers = parser.add_subparsers(dest='command')
    _ = subparsers.add_parser('images')
    pull_parser = subparsers.add_parser('pull')
    pull_parser.add_argument('image_names', nargs='+')
    args = vars(parser.parse_args())

    storage = make_storage(**args)

    match args.pop('command', None):
        case "images":
            list_images_command(storage, **args)
        case "pull":
            pull_image_command(storage, **args)
        case _:
            parser.print_help()
