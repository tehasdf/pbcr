import argparse

from pbcr.images import list_images_command, pull_image_command
from pbcr.run import run_command
from pbcr.storage import make_storage


def main():
    parser = argparse.ArgumentParser(
        prog='pbcr',
    )
    subparsers = parser.add_subparsers(dest='command')
    _ = subparsers.add_parser('images')

    pull_parser = subparsers.add_parser('pull')
    pull_parser.add_argument('image_names', nargs='+')

    run_parser = subparsers.add_parser('run')
    run_parser.add_argument('image_name', nargs=1)
    run_parser.add_argument(
        '-n',
        '--name',
        required=True,
        dest='container_name',
        help='Container name',
    )
    run_parser.add_argument(
        '-d',
        '--daemon',
        action='store_true',
        dest='daemon',
    )

    kwargs = vars(parser.parse_args())

    command = kwargs.pop('command', None)
    storage = make_storage(**kwargs)

    match command:
        case "images":
            list_images_command(storage, **kwargs)
        case "pull":
            pull_image_command(storage, **kwargs)
        case "run":
            image_name = kwargs.pop('image_name')[0]
            run_command(storage, image_name, **kwargs)
        case _:
            parser.print_help()
