"""TCP stack implementation

This implements the TCP-related networking and proxying.
"""
import asyncio
import enum
import threading
import typing as t

from dataclasses import dataclass

from pbcr.networking.ip import IPInfo
from pbcr.networking.utils import checksum


class TCPFlags(enum.IntEnum):
    """TCP flags for the flags field in the TCP header"""
    FIN = 0x01
    SYN = 0x02
    RST = 0x04
    PSH = 0x08
    ACK = 0x10
    URG = 0x20
    ECE = 0x40
    CWR = 0x80
    NS = 0x100


@dataclass
class TCPInfo:
    """TCP header information"""
    sport: int
    dport: int
    seq: int
    ack: int
    flags: int

    @classmethod
    def parse(cls, iph: IPInfo, data: bytearray) -> tuple[t.Self, bytearray]:
        """Parse TCP header from data"""
        pseudo_iph = bytearray([
            *iph.src,
            *iph.dst,
            0,
            6,
            *int.to_bytes(len(data), 2, "big"),
        ])
        if checksum(pseudo_iph + data) != 0:
            raise ValueError("Invalid checksum")
        sport = int.from_bytes(data[:2], "big")
        dport = int.from_bytes(data[2:4], "big")
        seq = int.from_bytes(data[4:8], "big")
        ack = int.from_bytes(data[8:12], "big")
        flags = data[13]
        return cls(sport, dport, seq, ack, flags), data[20:]

    def build(
        self,
        src_ip: bytes,
        dst_ip: bytes,
        data: bytearray,
    ) -> bytearray:
        """Build TCP header"""
        tcph = bytearray([
            *int.to_bytes(self.sport, 2, "big"),
            *int.to_bytes(self.dport, 2, "big"),
            *int.to_bytes(self.seq, 4, "big"),
            *int.to_bytes(self.ack, 4, "big"),
            5 << 4,  # data offset
            self.flags,
            *int.to_bytes(8192, 2, "big"),  # window size
            *int.to_bytes(0, 2, "big"),  # checksum
            *int.to_bytes(0, 2, "big"),  # urgent pointer
            *data,
        ])
        pseudo_iph = bytearray([
            *src_ip,
            *dst_ip,
            0,
            6,
            *int.to_bytes(len(tcph), 2, "big"),
        ])
        chck = checksum(pseudo_iph + tcph)
        tcph[16:18] = int.to_bytes(chck, 2, "big")

        return tcph

class TCPState(enum.Enum):
    """TCP state for the state field in the TCP Control Block"""
    LISTEN = enum.auto()
    SYN_SENT = enum.auto()
    SYN_RECEIVED = enum.auto()
    ESTABLISHED = enum.auto()
    FIN_WAIT_1 = enum.auto()
    FIN_WAIT_2 = enum.auto()
    CLOSE_WAIT = enum.auto()
    CLOSING = enum.auto()
    LAST_ACK = enum.auto()
    TIME_WAIT = enum.auto()
    CLOSED = enum.auto()


@dataclass
class _TCB:
    """TCP Control Block - tracks state for a TCP connection

    Attributes:
        src_ip: Source IP address
        dst_ip: Destination IP address
        src_port: Source port
        dst_port: Destination port
        snd_una: Oldest unacknowledged sequence number
        snd_nxt: Next sequence number to send
        snd_wnd: Send window size
        snd_up: Send urgent pointer
        snd_wl1: Sequence number used for last window update
        snd_wl2: Acknowledgment number used for last window update
        iss: Initial send sequence number
        rcv_nxt: Next sequence number expected to receive
        rcv_wnd: Receive window size
        rcv_up: Receive urgent pointer
        irs: Initial receive sequence number
        state: Current TCP state
        proxy_reader: asyncio.StreamReader for proxy connection
        proxy_writer: asyncio.StreamWriter for proxy connection
    """
    # pylint: disable=too-many-instance-attributes
    src_ip: bytes
    dst_ip: bytes
    src_port: int
    dst_port: int

    snd_una: int
    snd_nxt: int
    snd_wnd: int
    snd_up: int
    snd_wl1: int
    snd_wl2: int
    iss: int

    rcv_nxt: int
    rcv_wnd: int
    rcv_up: int
    irs: int

    state: TCPState
    proxy_reader: asyncio.StreamReader | None = None
    proxy_writer: asyncio.StreamWriter | None = None

    @property
    def key(self) -> tuple:
        """Key for this connection

        Use this for hashmaps
        """
        return (bytes(self.src_ip), self.src_port, bytes(self.dst_ip), self.dst_port)


class TCPStack:
    """TCP stack implementation"""
    def __init__(self, writer: t.Callable[[bytearray], None]):
        self.writer = writer
        self._tcb = {}
        self._loop = asyncio.new_event_loop()
        self.thread = None

    def start(self):
        """Start the TCP stack"""
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )
        self.thread.start()

    def _run(self):
        self._loop.run_forever()

    def handle_packet(
        self,
        iph: IPInfo,
        tcph: TCPInfo,
        data: bytearray,
    ):
        """Handle incoming TCP packet"""
        self._loop.call_soon_threadsafe(
            lambda: self._loop.create_task(
                self._do_handle(iph, tcph, data)
            )
        )


    def _get_tcb(self, iph: IPInfo, tcph: TCPInfo) -> _TCB | None:
        """Get TCB for this connection, creating if needed"""
        key = (bytes(iph.src), tcph.dport, bytes(iph.dst), tcph.sport)
        if key not in self._tcb:
            if not tcph.flags & TCPFlags.SYN:
                # Only create new TCB on SYN
                return None
            # Initialize new TCB
            self._tcb[key] = _TCB(
                src_ip=iph.src,
                dst_ip=iph.dst,
                src_port=tcph.dport,
                dst_port=tcph.sport,
                snd_una=0,
                snd_nxt=1,  # Initial sequence number
                snd_wnd=8192,
                snd_up=0,
                snd_wl1=0,
                snd_wl2=0,
                iss=1,  # Initial send sequence
                rcv_nxt=tcph.seq + 1,
                rcv_wnd=8192,
                rcv_up=0,
                irs=tcph.seq,  # Initial receive sequence
                state=TCPState.LISTEN
            )
        return self._tcb[key]

    def _build_response(
        self,
        tcb: _TCB,
        flags: int,
        data: bytearray = bytearray(),
    ) -> bytearray:
        """Build a TCP response packet"""
        return IPInfo(
            src=tcb.dst_ip,
            dst=tcb.src_ip,
            proto=6,
        ).build(20 + len(data)) + TCPInfo(
            dport=tcb.dst_port,
            sport=tcb.src_port,
            seq=tcb.snd_nxt,
            ack=tcb.rcv_nxt,
            flags=flags,
        ).build(
            tcb.dst_ip,
            tcb.src_ip,
            data,
        )

    def _send_response(self, response: bytearray, tcb: _TCB):
        """Send a response and update sequence number if needed"""
        self.writer(response)
        if response[33] & TCPFlags.SYN or response[33] & TCPFlags.FIN:
            tcb.snd_nxt += 1

    async def _handle_listen_state(
        self,
        tcph: TCPInfo,
        tcb: _TCB,
    ):
        """Handle SYN packet in LISTEN state"""
        if tcph.flags & TCPFlags.SYN:
            tcb.state = TCPState.SYN_RECEIVED

            reader, writer = await asyncio.open_connection(
                host='127.0.0.1',
                port=tcb.src_port,
            )
            tcb.proxy_reader = reader
            tcb.proxy_writer = writer
            response = self._build_response(
                tcb, TCPFlags.ACK | TCPFlags.SYN)
            self._send_response(response, tcb)

    async def _handle_syn_received_state(
        self,
        tcph: TCPInfo,
        tcb: _TCB,
    ):
        """Handle ACK packet in SYN_RECEIVED state"""
        if tcph.flags & TCPFlags.ACK:
            tcb.state = TCPState.ESTABLISHED
            print(
                f'Connection established: {tcb.src_ip}:{tcb.src_port} '
                f'-> {tcb.dst_ip}:{tcb.dst_port}'
            )
            # Start background task to read from proxy
            asyncio.create_task(self._proxy_reader_task(tcb))

    async def _handle_established_state(
        self,
        tcph: TCPInfo,
        tcb: _TCB,
        data: bytearray,
    ):
        """Handle packets in ESTABLISHED state"""
        if tcph.flags & TCPFlags.FIN:
            tcb.state = TCPState.CLOSE_WAIT
            response = self._build_response(tcb, TCPFlags.ACK)
            self._send_response(response, tcb)
        elif tcph.flags & TCPFlags.ACK:
            tcb.rcv_nxt = tcph.seq + len(data)
            response = self._build_response(tcb, TCPFlags.ACK)
            self._send_response(response, tcb)
            if data:
                if tcb.proxy_writer:
                    tcb.proxy_writer.write(data)
                    await tcb.proxy_writer.drain()

    async def _handle_close_wait_state(
        self,
        _tcph: TCPInfo,
        tcb: _TCB,
    ):
        """Handle CLOSE_WAIT state - send FIN"""
        tcb.state = TCPState.LAST_ACK
        response = self._build_response(tcb, TCPFlags.FIN | TCPFlags.ACK)
        self._send_response(response, tcb)

    async def _proxy_reader_task(
        self,
        tcb: _TCB,
    ):
        """Background task that reads from proxy connection and forwards data"""
        try:
            while tcb.state == TCPState.ESTABLISHED:
                data = await tcb.proxy_reader.read(8192)
                if not data:
                    # Connection closed by remote
                    response = self._build_response(tcb, TCPFlags.FIN | TCPFlags.ACK)
                    self._send_response(response, tcb)
                    tcb.state = TCPState.LAST_ACK
                    break

                # Forward data to client
                response = self._build_response(
                    tcb, TCPFlags.ACK | TCPFlags.PSH, bytearray(data))
                self._send_response(response, tcb)
                tcb.snd_nxt += len(data)

        except Exception as exc:
            print(f"Proxy reader error: {exc}")
            response = self._build_response(tcb, TCPFlags.FIN | TCPFlags.ACK)
            self._send_response(response, tcb)
            tcb.state = TCPState.LAST_ACK
            raise

    async def _handle_last_ack_state(
        self,
        tcph: TCPInfo,
        tcb: _TCB,
    ):
        """Handle LAST_ACK state - final ACK"""
        if tcph.flags & TCPFlags.ACK:
            tcb.state = TCPState.CLOSED
            del self._tcb[tcb.key]
            print(
                f'Connection closed: {tcb.src_ip}:{tcb.src_port} '
                f'-> {tcb.dst_ip}:{tcb.dst_port}'
            )

    async def _do_handle(
        self,
        iph: IPInfo,
        tcph: TCPInfo,
        data: bytearray,
    ):
        """Main TCP packet handler"""
        tcb = self._get_tcb(iph, tcph)
        if not tcb:
            return

        handlers = {
            TCPState.LISTEN: self._handle_listen_state,
            TCPState.SYN_RECEIVED: self._handle_syn_received_state,
            TCPState.CLOSE_WAIT: self._handle_close_wait_state,
            TCPState.LAST_ACK: self._handle_last_ack_state,
        }

        if tcb.state == TCPState.ESTABLISHED:
            await self._handle_established_state(tcph, tcb, data)
        if handler := handlers.get(tcb.state):
            await handler(tcph, tcb)
