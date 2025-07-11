"""Tests for the networking module."""

import http.server
import os
import pathlib
import socket
import threading
import time

import pytest

from scapy.layers.inet import IP, TCP

from pbcr.networking import checksum, IPInfo, TCPInfo
from pbcr.run import run_command
from pbcr.storage import FileImageStorage, FileContainerStorage
from pbcr.types import ContainerConfig


def test_ip_checksum():
    """Test the IP checksum function"""
    pck = IP(src="192.168.2.1", dst="192.168.2.2")
    assert checksum(pck.build()) == 0


def test_ip_parse():
    """Test parsing an IP header"""
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
    """Test building an IP header"""
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
    """Test parsing a TCP header"""
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
    """Test building a TCP header"""
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


@pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Integration test, requires connectivity",
)
@pytest.mark.asyncio
async def test_container_can_reach_http_server(tmp_path: pathlib.Path):
    """
    Integration test: Verify a container can reach an external HTTP server.
    """
    request_count = 0

    class SimpleHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
        """A simple HTTP request handler that counts requests."""
        def do_GET(self):  # pylint: disable=invalid-name
            """Handle GET requests."""
            nonlocal request_count
            request_count += 1
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"Hello from test server!")

    # Choose an available port
    server_address = ('127.0.0.1', 0) # 0 means OS will assign a free port
    httpd = http.server.HTTPServer(server_address, SimpleHTTPRequestHandler)

    # Get the actual port assigned by the OS
    _, port = httpd.socket.getsockname()

    # Start the server in a separate thread
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    try:
        # Give the server a moment to start up
        time.sleep(0.1)

        # Setup storage for pbcr
        image_storage = FileImageStorage.create(tmp_path / "images")
        container_storage = FileContainerStorage.create(tmp_path / "containers")

        # Define the container configuration
        # Use the actual host and port of the test server
        container_config = ContainerConfig(
            image_name="docker.io/library/alpine",
            entrypoint=f"/usr/bin/wget -O - http://192.168.64.2:{port}",
            daemon=False, # Run in foreground for the test
            remove=True, # Clean up container after test
            container_name="test-http-client",
            volumes=None,
        )

        # Run the container
        # This call will block until the container exits
        await run_command(image_storage, container_storage, container_config)

    finally:
        # Shut down the server
        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=1) # Wait for the thread to finish, with a timeout
    assert request_count > 0, "No requests were made to the test HTTP server."
