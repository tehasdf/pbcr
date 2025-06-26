"""Utilities for getting a process' network file descriptors."""

from dataclasses import dataclass
import array
import fcntl
import socket
import struct
import sys

from pbcr import libc
from pbcr.forkbarrier import ForkBarrier


@dataclass
class NetworkConfig:
    """Configuration for network interfaces"""
    tun_device: bytes = b'tap0'
    tun_ip: str = '192.168.64.1'
    tun_netmask: str = '255.255.255.0'
    tun_flags: int = libc.IFF_TUN | libc.IFF_NO_PI
    up_flags: int = libc.IFF_UP | libc.IFF_RUNNING

def _setup_network_namespaces(pid: int) -> None:
    """Enter the process's user and network namespaces.

    Args:
        pid: Process ID to enter namespaces of
    """
    with open(f'/proc/{pid}/ns/user', 'rb') as userns_file, \
            open(f'/proc/{pid}/ns/net', 'rb') as netns_file:
        libc.setns(userns_file.fileno(), libc.CLONE_NEWUSER)
        libc.setns(netns_file.fileno(), libc.CLONE_NEWNET)


def _create_tun_device(config: NetworkConfig) -> int:
    """Create and configure a TUN device.

    Args:
        config: Network configuration to use

    Returns:
        File descriptor of the created TUN device
    """
    ifreq = struct.pack(
        f"{libc.IFNAMSIZ}sH", 
        config.tun_device,
        config.tun_flags
    )
    # ignore pylint here, because we'll be returning the fd later
    tun_fd = open("/dev/net/tun", "r+b", buffering=0)  # pylint: disable=consider-using-with
    fcntl.ioctl(tun_fd, libc.TUNSETIFF, ifreq)
    return tun_fd

def _configure_network_interfaces(config: NetworkConfig) -> None:
    """Configure loopback and TAP interfaces.

    Args:
        config: Network configuration to apply
    """
    lo_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_fd = lo_sock.fileno()

    # Configure loopback interface
    fcntl.ioctl(
        sock_fd,
        libc.SIOCSIFFLAGS,
        struct.pack(f"{libc.IFNAMSIZ}sH", b'lo', config.up_flags)
    )
    # Configure TUN interface
    fcntl.ioctl(
        sock_fd,
        libc.SIOCSIFFLAGS,
        struct.pack(f"{libc.IFNAMSIZ}sH", config.tun_device, config.up_flags)
    )
    # Set IP address
    ip_bytes = socket.inet_aton(config.tun_ip)
    fcntl.ioctl(
        sock_fd,
        libc.SIOCSIFADDR,
        struct.pack('16sI14s', config.tun_device, socket.AF_INET, ip_bytes)
    )

    # Set netmask
    nm_bytes = socket.inet_aton(config.tun_netmask)
    fcntl.ioctl(
        sock_fd,
        libc.SIOCSIFNETMASK,
        struct.pack('16sI14s', config.tun_device, socket.AF_INET, nm_bytes)
    )


def _child_process_operations(
    pid: int,
    left_sock: socket.socket,
    barrier: ForkBarrier,
    config: NetworkConfig
) -> None:
    """Operations performed in the child process.

    Args:
        pid: Process ID to configure
        left_sock: Socket for communication
        barrier: Synchronization barrier
        config: Network configuration to apply
    """
    _setup_network_namespaces(pid)
    tun_fd = _create_tun_device(config)
    _configure_network_interfaces(config)

    barrier.signal()
    left_sock.sendmsg(
        [b'ok'],
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack('i', tun_fd.fileno()))]
    )
    barrier.wait()
    os._exit(0)

def get_process_net_fd(pid: int, config: NetworkConfig = None) -> int:
    """Get the network file descriptor for a process.

    Args:
        pid: Process ID to get FD for
        config: Optional network configuration

    Returns:
        Network file descriptor
    """
    if config is None:
        config = NetworkConfig()
    left_sock, right_sock = socket.socketpair()

    with ForkBarrier() as barrier:
        if barrier.is_child:
            _child_process_operations(pid, left_sock, barrier, config)

        barrier.wait()
        fds = array.array("i")
        parts = right_sock.recvmsg(4096, socket.CMSG_LEN(1 * fds.itemsize))

        for cmsg_level, cmsg_type, cmsg_data in parts[1]:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                data_end = len(cmsg_data) - (len(cmsg_data) % fds.itemsize)
                fds.frombytes(cmsg_data[:data_end])

        barrier.signal()
        return fds[0]
