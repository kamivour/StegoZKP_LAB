"""
tcp_sender.py — Timed TCP file sender for LAN throughput benchmarking.

Usage:
    python tcp_sender.py <receiver_ip> <file_path> [--port PORT] [--out-json PATH]

Example:
    python tcp_sender.py 192.168.1.50 results/paper_zk_1-04.png --out-json lan_result_caseA.json

Protocol:
    1. Connect to receiver.
    2. Send an 8-byte unsigned 64-bit integer (big-endian) = file size.
    3. Start timer, send entire file payload.
    4. Wait for 1-byte ACK from receiver.
    5. Stop timer, print results, write JSON result file.
"""

import argparse
import json
import socket
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HEADER_FMT = "!Q"    # big-endian unsigned 64-bit integer
CHUNK_SIZE  = 65536  # 64 KB send chunks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TCP sender for LAN throughput benchmark."
    )
    parser.add_argument("receiver_ip", help="IP address of the receiver machine")
    parser.add_argument("file_path",   help="Path to the stego PNG file to transmit")
    parser.add_argument("--port",     type=int, default=9000,
                        help="TCP port on receiver (default: 9000)")
    parser.add_argument("--out-json", default=None,
                        help="Path to write JSON result (default: lan_result_<stem>.json)")
    args = parser.parse_args()

    path = Path(args.file_path)
    if not path.is_file():
        print(f"[sender] ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    payload   = path.read_bytes()
    file_size = len(payload)
    header    = struct.pack(HEADER_FMT, file_size)

    json_out = Path(args.out_json) if args.out_json else Path(f"lan_result_{path.stem}.json")

    print(f"[sender] File      : {path}")
    print(f"[sender] File size : {file_size} bytes ({file_size / 1024:.2f} KB)")
    print(f"[sender] Connecting to {args.receiver_ip}:{args.port} …")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((args.receiver_ip, args.port))
        print(f"[sender] Connected.")

        # --- send size header (not timed) ---
        sock.sendall(header)

        # --- timed payload send ---
        t_start = time.perf_counter()
        offset  = 0
        while offset < file_size:
            sent = sock.send(payload[offset : offset + CHUNK_SIZE])
            if sent == 0:
                raise ConnectionError("Socket connection broken during send.")
            offset += sent

        # --- wait for ACK ---
        ack = b""
        while not ack:
            ack = sock.recv(1)
        t_end = time.perf_counter()

    elapsed        = t_end - t_start
    file_size_kb   = round(file_size / 1024, 2)
    throughput_mbps = round((file_size * 8 / 1_000_000) / elapsed, 3)
    elapsed_s      = round(elapsed, 6)

    # --- console report ---
    print()
    print("=" * 44)
    print("  TCP Sender — Benchmark Results")
    print("=" * 44)
    print(f"  File       : {path.name}")
    print(f"  File size  : {file_size_kb} KB")
    print(f"  Time       : {elapsed_s} s")
    print(f"  Throughput : {throughput_mbps} Mbps")
    print(f"  JSON saved : {json_out}")
    print("=" * 44)

    # --- write JSON result ---
    result = {
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "receiver_ip":    args.receiver_ip,
        "port":           args.port,
        "file":           str(path.name),
        "file_size_bytes": file_size,
        "file_size_kb":   file_size_kb,
        "elapsed_s":      elapsed_s,
        "throughput_mbps": throughput_mbps,
        "transport":      "TCP/LAN",
        "note":           "Sender-side measurement; timer starts after header, stops on ACK receipt."
    }
    json_out.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
