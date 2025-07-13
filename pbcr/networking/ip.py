"""IP header handling"""

import typing as t

from dataclasses import dataclass

from pbcr.networking.utils import checksum


@dataclass
class IPInfo:
    """IP header information"""
    src: bytes
    dst: bytes
    proto: int
    ipver: int = 4

    def build(self, datalen: int) -> bytearray:
        """Build the IP header"""
        ihl = 5
        ident = 1
        total_len = (ihl * 4) + datalen
        iph = bytearray([
            self.ipver << 4 | ihl,
            0,  # DSCP and ECN
            *int.to_bytes(total_len, 2, "big"),
            ident >> 8,
            ident & 0xFF,
            *int.to_bytes(0, 2, "big"),  # flags and fragment offset
            255,  # TTL
            self.proto,
            *int.to_bytes(0, 2, "big"),  # checksum
            *self.src,
            *self.dst,
        ])
        chck = checksum(iph)
        iph[10:12] = int.to_bytes(chck, 2, "big")
        return iph

    @classmethod
    def parse(cls, data: bytearray) -> tuple[t.Self, bytearray]:
        """Parse an IP header"""
        ihl = (data[0] & 0x0F) * 4
        cksum = checksum(data[:ihl])
        if cksum not in (0, 0xffff):
            raise ValueError(f"Invalid checksum: {hex(cksum)}")
        hdr = cls(
            ipver=(data[0] >> 4) & 0x0F,
            src=bytes(data[12:16]),
            dst=bytes(data[16:20]),
            proto=data[9],
        )
        return hdr, data[ihl:]
