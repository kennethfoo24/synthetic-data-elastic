import socket

from synthgen.syslog_gen.emitter import UdpSender


def test_udp_sender_delivers_datagram():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    port = rx.getsockname()[1]
    UdpSender("127.0.0.1", port).send("hello syslog")
    data, _ = rx.recvfrom(4096)
    assert data == b"hello syslog\n"
    rx.close()
