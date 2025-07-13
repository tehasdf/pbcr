"""Utilities for getting a process' network FD"""

import array
import fcntl
import os
import socket
import struct

from pbcr import libc


def _setup_network_namespaces(pid: int):
    """Set up user and network namespaces for the child process."""
    with open(f'/proc/{pid}/ns/user', 'rb') as userns_file, \
            open(f'/proc/{pid}/ns/net', 'rb') as netns_file:
        libc.setns(
            int(userns_file.fileno()),
            libc.CLONE_NEWUSER,
        )
        libc.setns(
            int(netns_file.fileno()),
            libc.CLONE_NEWNET,
        )

def _setup_tun_interface():
    """Set up the TUN interface and return its file descriptor."""
    dev_name = b'tun0'
    ifreq = struct.pack(
        f"{libc.IFNAMSIZ}sH",
        dev_name,
        libc.IFF_TUN | libc.IFF_NO_PI,
    )
    tun_fd = open("/dev/net/tun", "r+b", buffering=0)  # pylint: disable=consider-using-with
    fcntl.ioctl(tun_fd, libc.TUNSETIFF, ifreq)
    return tun_fd

def _configure_loopback_interface():
    """Configure the loopback interface."""
    lo_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_fd = lo_sock.fileno()
    lo_ifreq = struct.pack(
        f"{libc.IFNAMSIZ}sH",
        b'lo',
        libc.IFF_UP | libc.IFF_RUNNING,
    )
    fcntl.ioctl(sock_fd, libc.SIOCSIFFLAGS, lo_ifreq)
    lo_sock.close() # Close the socket after use

def _configure_tun_interface():
    """Configure the TUN interface with IP address and netmask."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_fd = sock.fileno()

    dev_name = b'tun0'
    fcntl.ioctl(
        sock_fd,
        libc.SIOCSIFFLAGS,
        struct.pack(
            f"{libc.IFNAMSIZ}sH",
            dev_name,
            libc.IFF_UP | libc.IFF_RUNNING,
        )
    )
    ip_text = '192.168.64.1'
    ip_bytes = socket.inet_aton(ip_text)
    fcntl.ioctl(
        sock_fd,
        libc.SIOCSIFADDR,
        struct.pack('16sI14s', b'tun0', socket.AF_INET, ip_bytes)
    )
    nm_text = '255.255.255.0'
    nm_bytes = socket.inet_aton(nm_text)
    fcntl.ioctl(
        sock_fd,
        libc.SIOCSIFNETMASK,
        struct.pack('16sI14s', b'tun0', socket.AF_INET, nm_bytes),
    )
    sock.close() # Close the socket after use

def _send_fd_to_parent(sock: socket.socket, fd):
    """Send a file descriptor to the parent process."""
    sock.sendmsg(
        [b'ok'],
        [
            (
                socket.SOL_SOCKET,
                socket.SCM_RIGHTS,
                struct.pack('i', fd.fileno())
            )
        ],
    )

def receive_process_net_fd(sock: socket.socket) -> int:
    """Receive a file descriptor from the child process."""
    fds = array.array("i")
    parts = sock.recvmsg(4096, socket.CMSG_LEN(1 * fds.itemsize))
    ancdata = parts[1]
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (
            cmsg_level == socket.SOL_SOCKET and
            cmsg_type == socket.SCM_RIGHTS
        ):
            # Append data, ignoring any truncated integers at the end.
            data_end = len(cmsg_data) - (len(cmsg_data) % fds.itemsize)
            fds.frombytes(cmsg_data[:data_end])
    return fds[0]


def send_process_net_fd(sock: socket.socket):
    """Send the network FD for a process to the parent"""
    pid = os.getpid()
    _setup_network_namespaces(pid)
    tun_fd = _setup_tun_interface()
    _configure_loopback_interface()
    _configure_tun_interface()

    _send_fd_to_parent(sock, tun_fd)
