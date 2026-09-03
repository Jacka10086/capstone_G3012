#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODES: dict[str, int] = {
    "off": 0,
    "low": 500,
    "high": 3000,
    "panic": 10000,
    "critical": 15000,
}
DEFAULT_SOCKETS = 20
DEFAULT_PACKET_SIZE = 256
DEFAULT_SOURCE_PORT_BASE = 40000


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


def read_mode_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip().lower()
    except (OSError, FileNotFoundError):
        return "off"


def resolve_mode(mode: str, modes: dict[str, int] | None = None) -> tuple[str, int]:

    mapping = {**DEFAULT_MODES, **(modes or {})}
    normalized = mode.strip().lower()
    if normalized not in mapping:
        normalized = "off"
    return normalized, mapping[normalized]


class ZombieTrafficGenerator:

    def __init__(
        self,
        target_host: str,
        target_port: int,
        packet_size: int,
        mode_file: Path,
        output_path: Path,
        state_path: Path,
        metrics_interval: float,
        sockets: int = DEFAULT_SOCKETS,
        modes: dict[str, int] | None = None,
    ) -> None:
        self.target_host = target_host
        self.target_port = target_port
        self.packet_size = packet_size
        self.mode_file = mode_file
        self.output_path = output_path
        self.state_path = state_path
        self.metrics_interval = metrics_interval
        self.sockets = max(1, sockets)
        self.modes = modes if modes is not None else dict(DEFAULT_MODES)

        self.packets_sent: int = 0
        self.bytes_sent: int = 0
        self.errors: int = 0
        self.sequence: int = 0
        self.running: bool = True
        self.last_error: str = ""
        self.mode, self.rate = resolve_mode(read_mode_file(self.mode_file), self.modes)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)



    def _handle_signal(self, signum: int, frame: Any) -> None:
        del signum, frame
        self.stop()

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()



    def _build_payload(self, zombie_id: int, seq: int) -> bytes:
        payload: dict[str, Any] = {
            "zombie": f"z-{zombie_id:02d}",
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cmd": "flood",
            "target": self.target_host,
            "port": self.target_port,
            "seq": seq,
            "pad": "",
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(encoded) < self.packet_size:
            payload["pad"] = "x" * (self.packet_size - len(encoded))
            encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return encoded



    def _create_sockets(self) -> list[socket.socket]:
        socks: list[socket.socket] = []
        for index in range(self.sockets):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

                sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, 4)
                source_port = DEFAULT_SOURCE_PORT_BASE + index
                try:
                    sock.bind(("0.0.0.0", source_port))
                except OSError:

                    pass
                socks.append(sock)
            except OSError as exc:
                self.last_error = str(exc)
        if not socks:
            raise RuntimeError("could not create any UDP sockets")
        return socks

    def _close_sockets(self, socks: list[socket.socket]) -> None:
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass



    def _metrics_loop(self) -> None:
        while not self._stop_event.wait(self.metrics_interval):
            self._flush()

    def _flush(self) -> None:
        self._write_metrics()
        self._save_state()

    def _write_metrics(self) -> None:
        with self._lock:
            packets = self.packets_sent
            byte_count = self.bytes_sent
            err_count = self.errors
            is_up = self.running
            mode = self.mode
            rate = self.rate

        labels = f'target="{self.target_host}",port="{self.target_port}",mode="{mode}"'
        lines = [
            "# HELP capstone_zombie_up Whether the zombie traffic generator service is running.",
            "# TYPE capstone_zombie_up gauge",
            f"capstone_zombie_up{{{labels}}} {1 if is_up else 0}",
            "# HELP capstone_zombie_enabled Whether the zombie traffic generator is actively sending packets.",
            "# TYPE capstone_zombie_enabled gauge",
            f"capstone_zombie_enabled{{{labels}}} {1 if rate > 0 else 0}",
            "# HELP capstone_zombie_mode_info The currently active zombie traffic mode.",
            "# TYPE capstone_zombie_mode_info gauge",
            f'capstone_zombie_mode_info{{mode="{mode}"}} 1',
            "# HELP capstone_zombie_packets_total Zombie UDP packets sent since start.",
            "# TYPE capstone_zombie_packets_total counter",
            f"capstone_zombie_packets_total{{{labels}}} {packets}",
            "# HELP capstone_zombie_bytes_total Zombie UDP payload bytes sent since start.",
            "# TYPE capstone_zombie_bytes_total counter",
            f"capstone_zombie_bytes_total{{{labels}}} {byte_count}",
            "# HELP capstone_zombie_errors_total Socket errors encountered while sending.",
            "# TYPE capstone_zombie_errors_total counter",
            f"capstone_zombie_errors_total{{{labels}}} {err_count}",
            "# HELP capstone_zombie_target_rate_packets_per_second Configured packet rate for the active mode.",
            "# TYPE capstone_zombie_target_rate_packets_per_second gauge",
            f"capstone_zombie_target_rate_packets_per_second{{{labels}}} {rate}",
        ]
        atomic_write(self.output_path, "\n".join(lines) + "\n")

    def _save_state(self) -> None:
        with self._lock:
            state = {
                "packets_sent": self.packets_sent,
                "bytes_sent": self.bytes_sent,
                "errors": self.errors,
                "sequence": self.sequence,
            }
        atomic_write(self.state_path, json.dumps(state, sort_keys=True), 0o600)

    def _restore_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                return
            with self._lock:
                self.packets_sent = max(0, int(state.get("packets_sent", 0)))
                self.bytes_sent = max(0, int(state.get("bytes_sent", 0)))
                self.errors = max(0, int(state.get("errors", 0)))
                self.sequence = max(0, int(state.get("sequence", 0)))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
            pass



    def run(self) -> int:
        self._restore_state()

        metrics_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        metrics_thread.start()

        socks = self._create_sockets()
        try:
            addr = (self.target_host, self.target_port)
            tokens = 0.0
            last_tick = time.perf_counter()

            bucket_cap = max(1.0, float(self.rate))
            zombie_index = 0
            sock_index = 0

            while self.running:
                if self.rate <= 0:
                    self._stop_event.wait(0.1)
                    continue

                now = time.perf_counter()
                elapsed = now - last_tick
                last_tick = now
                tokens = min(tokens + elapsed * self.rate, bucket_cap)

                while tokens >= 1.0 and self.running:
                    payload = self._build_payload(zombie_index, self.sequence)
                    sock = socks[sock_index % len(socks)]
                    try:
                        sock.sendto(payload, addr)
                        with self._lock:
                            self.packets_sent += 1
                            self.bytes_sent += self.packet_size
                    except OSError as exc:
                        with self._lock:
                            self.errors += 1
                        self.last_error = str(exc)


                        try:
                            sock.close()
                        except OSError:
                            pass
                        try:
                            new_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            new_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                            new_sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, 4)
                            socks[sock_index % len(socks)] = new_sock
                        except OSError:
                            pass

                    self.sequence += 1
                    zombie_index = (zombie_index + 1) % self.sockets
                    sock_index += 1
                    tokens -= 1.0



                self._stop_event.wait(0.0001)
        finally:
            self.stop()
            self._close_sockets(socks)
            metrics_thread.join(timeout=self.metrics_interval + 1.0)
            self._flush()

            try:
                self.output_path.unlink()
            except FileNotFoundError:
                pass
        return 0





def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capstone zombie IoT traffic generator")
    parser.add_argument("--target", required=True, help="Target hostname / IP")
    parser.add_argument("--port", type=int, default=19999, help="Target UDP port (blocked by Snort)")
    parser.add_argument("--packet-size", type=int, default=DEFAULT_PACKET_SIZE, help="UDP payload size in bytes")
    parser.add_argument("--sockets", type=int, default=DEFAULT_SOCKETS, help="Number of UDP sockets/source ports")
    parser.add_argument("--mode-file", type=Path, required=True, help="File containing the active mode (off/low/high/panic)")
    parser.add_argument("--output", type=Path, required=True, help="Prometheus textfile output path")
    parser.add_argument("--state", type=Path, required=True, help="Persistent state file path")
    parser.add_argument("--metrics-interval", type=float, default=15.0, help="Seconds between metric flushes")
    parser.add_argument("--rate", type=int, default=0, help="Override the resolved mode rate (packets per second)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gen = ZombieTrafficGenerator(
        target_host=args.target,
        target_port=args.port,
        packet_size=args.packet_size,
        mode_file=args.mode_file,
        output_path=args.output,
        state_path=args.state,
        metrics_interval=args.metrics_interval,
        sockets=args.sockets,
    )
    if args.rate > 0:
        gen.rate = args.rate
    return gen.run()


if __name__ == "__main__":
    raise SystemExit(main())
