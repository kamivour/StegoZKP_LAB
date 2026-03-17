"""
benchmarks/run_network_benchmarks.py
======================================
TEST N2 — End-to-end HTTP/TCP loopback pipeline benchmark.

For each of the three test DICOMs (1-04 / 1-10 / 1-06):
  1. Starts a local HTTP server on a random loopback port.
  2. Runs the full embed pipeline (with Groth16 ZK proof) from scratch.
  3. HTTP POST-transfers the resulting stego PNG to the local server.
  4. Records:
       - Payload size (KB)  — stego PNG on disk
       - Total time (s)     — wall-clock from embed start to server ACK
       - Throughput (Mbps)  — payload / total_time * 8
       - Packets            — TCP segments estimated from recv(MSS) call count

Output: benchmarks/results/paper_network.json
        (human-readable summary printed to stdout)

Run from ImageLevel/:
    python benchmarks/run_network_benchmarks.py
"""

import gzip
import io
import json
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks._common import load_chaos_key, save_results
from src.zk_stego.dicom_handler import DicomStego, DEFAULT_PROOF_KEY

# ---------------------------------------------------------------------------
# TCP MSS for packet estimation on loopback
# ---------------------------------------------------------------------------
TCP_MSS = 1460          # standard Ethernet MSS used for packet count estimate

# ---------------------------------------------------------------------------
# Loopback HTTP server
# ---------------------------------------------------------------------------

class _RecvCountHandler(BaseHTTPRequestHandler):
    """Minimal HTTP server that accepts a POST, counts receive chunks, ACKs."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        received = 0
        chunks = 0
        while received < content_length:
            to_read = min(TCP_MSS, content_length - received)
            chunk = self.rfile.read(to_read)
            if not chunk:
                break
            received += len(chunk)
            chunks += 1
        self.server.received_bytes = received
        self.server.recv_chunks = chunks
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, fmt, *args):
        pass  # suppress access log


def _start_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _RecvCountHandler)
    server.received_bytes = 0
    server.recv_chunks = 0
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    return server


# ---------------------------------------------------------------------------
# Per-test benchmark
# ---------------------------------------------------------------------------

def benchmark_case(label: str, dcm_path: Path) -> dict:
    print(f"\n{'='*60}")
    print(f"  {label}  ({dcm_path.name})")
    print(f"{'='*60}")

    chaos_key = load_chaos_key()
    results_dir = ROOT / "benchmarks" / "results"
    stego_out = results_dir / f"net_e2e_{dcm_path.stem}.png"

    # ── Start timing BEFORE embed ────────────────────────────────────────────
    print("  [1/3] Embed (with ZK proof) … ", flush=True)
    t_pipeline_start = time.perf_counter()

    DicomStego(project_root=str(ROOT)).embed(
        str(dcm_path), str(stego_out),
        chaos_key=chaos_key,
        proof_key=DEFAULT_PROOF_KEY,
        generate_zk_proof=True,
        verbose=False,
    )
    t_after_embed = time.perf_counter()
    embed_s = t_after_embed - t_pipeline_start
    payload_bytes = stego_out.stat().st_size
    payload_kb = payload_bytes / 1024
    print(f"  done ({embed_s:.2f} s)  file={payload_kb:.2f} KB")

    # ── HTTP loopback transfer ───────────────────────────────────────────────
    print("  [2/3] HTTP loopback transfer … ", end="", flush=True)
    server = _start_server()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"

    with open(str(stego_out), "rb") as f:
        data = f.read()

    t_xfer_start = time.perf_counter()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.URLError as e:
        print(f"\n  ERROR during HTTP transfer: {e}")
        raise
    t_xfer_end = time.perf_counter()

    xfer_s = t_xfer_end - t_xfer_start
    total_s = t_xfer_end - t_pipeline_start

    packets = server.recv_chunks
    throughput_mbps = (payload_bytes * 8) / total_s / 1e6   # total pipeline throughput
    xfer_throughput_mbps = (payload_bytes * 8) / xfer_s / 1e6 if xfer_s > 0 else 0

    print(f"done ({xfer_s*1000:.1f} ms)  chunks={packets}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"  [3/3] Summary:")
    print(f"    Payload          : {payload_kb:.2f} KB ({payload_bytes} bytes)")
    print(f"    Embed time (PG)  : {embed_s:.2f} s")
    print(f"    Transfer time    : {xfer_s*1000:.1f} ms")
    print(f"    Total time       : {total_s:.2f} s")
    print(f"    Pipeline thrput  : {throughput_mbps:.4f} Mbps")
    print(f"    Wire thrput      : {xfer_throughput_mbps:.1f} Mbps")
    print(f"    Recv chunks/pkts : {packets}")

    # Clean up temp net file
    if stego_out.exists():
        stego_out.unlink()

    return {
        "label":             label,
        "dicom_file":        dcm_path.name,
        "payload_bytes":     payload_bytes,
        "payload_kb":        round(payload_kb, 2),
        "embed_s":           round(embed_s, 3),
        "xfer_s":            round(xfer_s, 4),
        "total_s":           round(total_s, 3),
        "throughput_mbps":   round(throughput_mbps, 4),
        "xfer_throughput_mbps": round(xfer_throughput_mbps, 1),
        "recv_chunks":       packets,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\nE2E HTTP/TCP Loopback Benchmark (single-machine, localhost)\n")

    dicom_dir = ROOT / "examples" / "dicom"
    ordered = [
        ("MR T1 phantom (case A)", dicom_dir / "1-04.dcm"),
        ("MR T1 phantom (case B)", dicom_dir / "1-10.dcm"),
        ("MR T1 phantom (case C)", dicom_dir / "1-06.dcm"),
    ]

    all_results = []
    for label, dcm in ordered:
        r = benchmark_case(label, dcm)
        all_results.append(r)

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("NETWORK RESULTS SUMMARY")
    print(f"{'='*80}")
    print(f"{'Test Case':<30} {'KB':>8} {'Total(s)':>10} {'Mbps':>10} {'Pkts':>6}")
    print("-" * 70)
    for r in all_results:
        print(f"{r['label']:<30} {r['payload_kb']:>8.2f} {r['total_s']:>10.2f} "
              f"{r['throughput_mbps']:>10.4f} {r['recv_chunks']:>6}")

    total_min = min(r["total_s"] for r in all_results)
    total_max = max(r["total_s"] for r in all_results)
    print(f"\n  Total pipeline time range: {total_min:.2f} s – {total_max:.2f} s")

    save_results("paper_network.json", {"results": all_results})
    print("\nSaved → benchmarks/results/paper_network.json")


if __name__ == "__main__":
    main()
