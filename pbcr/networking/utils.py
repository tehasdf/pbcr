"""Utility functions for the IP stack"""


def checksum(data: bytes) -> int:
    """Compute an IP checksum"""
    # ignore because `s` is a perfectly good name for checksum
    # pylint: disable=invalid-name
    if len(data) % 2:
        data += b'\0'

    s = 0
    # Sum 16-bit words
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i+1]
        s += word

    # Fold carries
    s = (s >> 16) + (s & 0xffff)
    s += s >> 16

    return ~s & 0xffff
