#!/usr/bin/env python3

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RUNNING = True


def _handle_signal(signum: int, frame: object) -> None:
    global RUNNING
    RUNNING = False


def atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def run_burst(args: argparse.Namespace) -> dict:
    cmd = [
        args.iperf3,
        "-c", args.server,
        "-p", str(args.port),
        "-u",
        "-b", args.bandwidth,
        "-l", str(args.length),
        "-t", str(args.duration),
        "-J",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=args.duration + 10
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    end = data.get("end", {})
    received = end.get("sum_received", {})
    sent = end.get("sum_sent", {})
    if not received:
        return {}
    return {
        "throughput_bps": received.get("bits_per_second", 0.0),
        "jitter_seconds": received.get("jitter_ms", 0.0) / 1000.0,
        "lost_packets": received.get("lost_packets", 0),
        "sent_packets": sent.get("packets", 0),
    }


def render_metrics(metrics: dict, labels: str) -> str:
    lines = [
        "# HELP capstone_iperf_throughput_bits_per_second Live UDP throughput of the iperf3 background client.",
        "# TYPE capstone_iperf_throughput_bits_per_second gauge",
        f"capstone_iperf_throughput_bits_per_second{{{labels}}} {metrics.get('throughput_bps', 0.0)}",
        "# HELP capstone_iperf_jitter_seconds Live UDP jitter of the iperf3 background client.",
        "# TYPE capstone_iperf_jitter_seconds gauge",
        f"capstone_iperf_jitter_seconds{{{labels}}} {metrics.get('jitter_seconds', 0.0)}",
        "# HELP capstone_iperf_loss_ratio Live UDP packet loss ratio of the iperf3 background client.",
        "# TYPE capstone_iperf_loss_ratio gauge",
        f"capstone_iperf_loss_ratio{{{labels}}} {metrics.get('loss_ratio', 0.0)}",
        "# HELP capstone_iperf_up Whether the iperf3 background client is running.",
        "# TYPE capstone_iperf_up gauge",
        f"capstone_iperf_up{{{labels}}} {1 if metrics else 0}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iperf3", default="/run/current-system/sw/bin/iperf3")
    parser.add_argument("--server", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bandwidth", default="100M")
    parser.add_argument("--length", type=int, default=1400)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    labels = f'source="iot",target="broker",protocol="udp"'
    output: Path = args.output

    while RUNNING:
        metrics = run_burst(args)
        if metrics:
            sent = metrics.get("sent_packets", 0)
            lost = metrics.get("lost_packets", 0)
            metrics["loss_ratio"] = lost / sent if sent else 0.0
        atomic_write(output, render_metrics(metrics, labels))

        deadline = time.monotonic() + args.interval
        while RUNNING and time.monotonic() < deadline:
            time.sleep(0.5)


    try:
        output.unlink()
    except FileNotFoundError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
