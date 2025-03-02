import array
import fcntl
import socket
import struct
import sys

from pbcr import libc
from pbcr.forkbarrier import ForkBarrier


def get_process_net_fd(pid) -> int:

    left_sock, right_sock = socket.socketpair()
    with ForkBarrier() as barrier:
        if barrier.is_child:
            with open(f'/proc/{pid}/ns/user') as userns_file, \
                    open(f'/proc/{pid}/ns/net') as netns_file:

                libc.setns(
                    int(userns_file.fileno()),
                    libc.CLONE_NEWUSER,
                )
                libc.setns(
                    int(netns_file.fileno()),
                    libc.CLONE_NEWNET,
                )

            dev_name = b'tap0'
            ifreq = struct.pack(
                "{}sH".format(libc.IFNAMSIZ),
                dev_name,
                libc.IFF_TUN | libc.IFF_NO_PI,
            )
            fd = open("/dev/net/tun", "r+b", buffering=0)
            fcntl.ioctl(fd, libc.TUNSETIFF, ifreq)

            lo_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock_fd = lo_sock.fileno()
            lo_ifreq = struct.pack(
                "{}sH".format(libc.IFNAMSIZ),
                b'lo',
                libc.IFF_UP | libc.IFF_RUNNING,
            )
            fcntl.ioctl(sock_fd, libc.SIOCSIFFLAGS, lo_ifreq)

            fcntl.ioctl(
                sock_fd,
                libc.SIOCSIFFLAGS,
                struct.pack(
                    "{}sH".format(libc.IFNAMSIZ),
                    dev_name,
                    libc.IFF_UP | libc.IFF_RUNNING,
                )
            )
            ip_text = '192.168.64.1'
            ip_bytes = socket.inet_aton(ip_text)
            fcntl.ioctl(
                sock_fd,
                libc.SIOCSIFADDR,
                struct.pack('16sI14s', b'tap0', socket.AF_INET, ip_bytes)
            )
            nm_text = '255.255.255.0'
            nm_bytes = socket.inet_aton(nm_text)
            fcntl.ioctl(
                sock_fd,
                libc.SIOCSIFNETMASK,
                struct.pack('16sI14s', b'tap0', socket.AF_INET, nm_bytes),
            )
            barrier.signal()
            left_sock.sendmsg(
                [b'ok'],
                [
                    (
                        socket.SOL_SOCKET,
                        socket.SCM_RIGHTS,
                        struct.pack('i', fd.fileno())
                    )
                ],
            )
            barrier.wait()
            sys.exit(0)

        barrier.wait()
        fds = array.array("i")
        parts = right_sock.recvmsg(4096, socket.CMSG_LEN(1 * fds.itemsize))
        ancdata = parts[1]
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if (
                cmsg_level == socket.SOL_SOCKET and
                cmsg_type == socket.SCM_RIGHTS
            ):
                # Append data, ignoring any truncated integers at the end.
                data_end = len(cmsg_data) - (len(cmsg_data) % fds.itemsize)
                fds.frombytes(cmsg_data[:data_end])
        barrier.signal()
        return fds[0]
