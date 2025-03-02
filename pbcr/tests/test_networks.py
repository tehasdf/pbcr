import socket

from scapy.layers.inet import IP, TCP

from pbcr.networking import checksum, IPInfo, TCPInfo


def test_ip_checksum():
    pck = IP(src="192.168.2.1", dst="192.168.2.2")
    assert checksum(pck.build()) == 0


def test_ip_parse():
    pck = IP(src="192.168.2.1", dst="192.168.2.2")
    data = bytearray(pck.build())
    # now data is:
    #    b'E\x00\x00\x14\x00\x01\x00\x00@\x00'
    #    b'\xf5\x95\xc0\xa8\x02\x01\xc0\xa8\x02\x02'
    hdr, data = IPInfo.parse(data)
    assert hdr.src == socket.inet_aton(pck.src)
    assert hdr.dst == socket.inet_aton(pck.dst)
    assert not data


def test_ip_build():
    pck = IP(src="192.168.2.1", dst="192.168.2.2", ttl=255)
    data = bytearray(pck.build())
    iph = IPInfo(
        src=socket.inet_aton(pck.src),
        dst=socket.inet_aton(pck.dst),
        proto=0,
    )
    built = iph.build(0)
    assert data == built


def test_parse_tcp():
    pck = (
        IP(src="192.168.2.1", dst="192.168.2.2") /
        TCP(sport=1234, dport=80, ack=123, seq=456, flags=2)
    )
    data = pck.build()
    iph, ipdata = IPInfo.parse(data)

    parsed, data = TCPInfo.parse(iph, ipdata)
    assert parsed.sport == 1234
    assert parsed.dport == 80
    assert parsed.seq == 456
    assert parsed.ack == 123
    assert parsed.flags == 2


def test_tcp_build():
    pck = (
        IP(src="192.168.2.1", dst="192.168.2.2", ttl=255) /
        TCP(sport=1234, dport=80, ack=123, seq=456, flags=2)
    )
    data = bytearray(pck.build())
    iph = IPInfo(
        src=socket.inet_aton(pck.src),
        dst=socket.inet_aton(pck.dst),
        proto=6,
    )
    tcph = TCPInfo(
        sport=pck.sport,
        dport=pck.dport,
        seq=pck.seq,
        ack=pck.ack,
        flags=2,
    )

    built_tcp = tcph.build(iph.src, iph.dst, bytearray())
    built_ip = iph.build(len(built_tcp))
    built = built_ip + built_tcp
    assert built == data
