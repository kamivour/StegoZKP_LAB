"""
tcp_receiver.py — Timed TCP file receiver for LAN throughput benchmarking.

Usage:
    python tcp_receiver.py [--port PORT] [--output OUTPUT]

Defaults:
    port   = 9000
    output = received_stego.png

Protocol:
    1. Sender connects.
    2. Sender sends an 8-byte unsigned 64-bit integer (big-endian) = file size.
    3. Receiver starts timer, reads exactly that many bytes.
    4. Receiver stops timer, sends 1-byte ACK (0x06).
    5. Receiver prints and saves results.
"""

import argparse
import socket
import struct
import time

HEADER_FMT = "!Q"          # big-endian unsigned 64-bit integer
HEADER_LEN = struct.calcsize(HEADER_FMT)
ACK_BYTE    = b"\x06"
CHUNK_SIZE  = 65536         # 64 KB recv chunks


def recv_exact(sock: socket.socket, n: int) -> bytearray:
    """Read exactly n bytes from sock, blocking until complete."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(CHUNK_SIZE, n - len(buf)))
        if not chunk:
            raise ConnectionError(
                f"Connection closed after {len(buf)}/{n} bytes."
            )
        buf.extend(chunk)
    return buf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TCP receiver for LAN throughput benchmark."
    )
    parser.add_argument("--port",   type=int, default=9000, help="TCP listen port (default: 9000)")
    parser.add_argument("--output", default="received_stego.png", help="Path to save received file (default: received_stego.png)")
    args = parser.parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", args.port))
        srv.listen(1)
        print(f"[receiver] Listening on 0.0.0.0:{args.port} …")

        conn, addr = srv.accept()
        with conn:
            print(f"[receiver] Connection from {addr[0]}:{addr[1]}")

            # --- read 8-byte size header ---
            header_raw = recv_exact(conn, HEADER_LEN)
            (file_size,) = struct.unpack(HEADER_FMT, header_raw)
            print(f"[receiver] Expecting {file_size} bytes ({file_size / 1024:.2f} KB)")

            # --- timed payload receive ---
            t_start = time.perf_counter()
            payload = recv_exact(conn, file_size)
            t_end   = time.perf_counter()

            # --- send ACK ---
            conn.sendall(ACK_BYTE)

        elapsed    = t_end - t_start
        throughput = (file_size * 8 / 1_000_000) / elapsed   # Mbps

        # --- save to disk ---
        with open(args.output, "wb") as f:
            f.write(payload)

        # --- report ---
        print()
        print("=" * 44)
        print("  TCP Receiver — Benchmark Results")
        print("=" * 44)
        print(f"  File size  : {file_size / 1024:.2f} KB")
        print(f"  Time       : {elapsed:.6f} s")
        print(f"  Throughput : {throughput:.3f} Mbps")
        print(f"  Saved to   : {args.output}")
        print("=" * 44)


if __name__ == "__main__":
    main()
