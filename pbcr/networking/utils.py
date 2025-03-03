"""Utility functions for the IP stack"""

import array


def checksum(data: bytes) -> int:
    """Compute an IP checksum"""
    # ignore because `s` is a perfectly good name for checksum
    # pylint: disable=invalid-name
    if len(data) % 2:
        data += b'\0'
    s = sum(array.array('H', data))
    s = (s >> 16) + (s & 0xffff)
    s += s >> 16
    return ~s & 0xffff
