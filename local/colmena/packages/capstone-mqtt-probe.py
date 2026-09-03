#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


@dataclass
class Sample:
    published_at: float
    acked_at: float | None = None
    failed: bool = False


class MqttProbe:

    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        topic: str,
        client_id: str,
        rate_per_second: float,
        payload_size: int,
        qos: int,
        output_path: Path,
        state_path: Path,
        metrics_interval: float,
        window_seconds: float,
        mqtt_module: Any = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be greater than zero")
        if payload_size <= 0:
            raise ValueError("payload_size must be greater than zero")
        if qos not in {0, 1, 2}:
            raise ValueError("qos must be 0, 1, or 2")
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic = topic
        self.client_id = client_id
        self.rate_per_second = rate_per_second
        self.payload_size = payload_size
        self.qos = qos
        self.output_path = output_path
        self.state_path = state_path
        self.metrics_interval = metrics_interval
        self.window_seconds = window_seconds
        self.mqtt = mqtt if mqtt_module is None else mqtt_module
        self.wall_clock = wall_clock

        self.samples: list[Sample] = []
        self.running = False
        self.connected = False
        self.ever_connected = False
        self.reconnects = 0
        self.publish_errors = 0
        self.last_error = ""
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pending: dict[int, Sample] = {}
        self._next_mid = 1

    def _handle_signal(self, signum: int, frame: object) -> None:
        del signum, frame
        self.stop()

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()

    def _on_connect(self, reason_code: Any) -> None:
        failed = getattr(reason_code, "is_failure", reason_code != 0)
        with self._lock:
            if failed:
                self.connected = False
                self.last_error = f"MQTT connect failed: {reason_code}"
                return
            if self.ever_connected and not self.connected:
                self.reconnects += 1
            self.connected = True
            self.ever_connected = True
            self.last_error = ""

    def _on_disconnect(self, reason_code: Any) -> None:
        with self._lock:
            self.connected = False
            if reason_code not in (0, None):
                self.last_error = f"MQTT disconnect: {reason_code}"

    def _on_publish(self, mid: int) -> None:
        with self._lock:
            sample = self._pending.pop(mid, None)
            if sample is None:
                return
            sample.acked_at = self.wall_clock()

    def _make_client(self) -> Any:
        client = self.mqtt.Client(
            client_id=self.client_id,
            callback_api_version=self.mqtt.CallbackAPIVersion.VERSION2,
            protocol=self.mqtt.MQTTv311,
        )
        client.on_connect = lambda client, userdata, flags, reason_code, properties: self._on_connect(reason_code)
        client.on_disconnect = lambda client, userdata, flags, reason_code, properties: self._on_disconnect(reason_code)
        client.on_publish = lambda client, userdata, mid, reason_code, properties: self._on_publish(mid)
        return client

    def _publish_once(self, client: Any, sequence: int) -> bool:
        payload = "x" * self.payload_size
        with self._lock:
            sample = Sample(published_at=self.wall_clock())
            if self.qos == 0:

                sample.acked_at = sample.published_at
        try:
            result = client.publish(self.topic, payload, qos=self.qos)
        except Exception as exc:
            with self._lock:
                sample.failed = True
                self.publish_errors += 1
                self.last_error = f"publish error: {exc}"
            return False
        success_code = getattr(self.mqtt, "MQTT_ERR_SUCCESS", 0)
        if getattr(result, "rc", success_code) != success_code:
            with self._lock:
                sample.failed = True
                self.publish_errors += 1
                self.last_error = f"publish error: rc={result.rc}"
            return False
        if self.qos > 0:
            with self._lock:
                self._pending[result.mid] = sample
        with self._lock:
            self.samples.append(sample)
        return True

    def _trim_samples(self, now: float) -> None:
        cutoff = now - self.window_seconds
        with self._lock:
            self.samples = [s for s in self.samples if s.published_at > cutoff]

            stale_mids = [
                mid for mid, sample in self._pending.items()
                if sample.published_at < cutoff
            ]
            for mid in stale_mids:
                self._pending.pop(mid, None)

    def _metrics_loop(self) -> None:
        while not self._stop_event.wait(self.metrics_interval):
            self._flush()

    def _flush(self) -> None:
        self._write_metrics()
        self._save_state()

    def _aggregate(self, now: float) -> dict[str, float]:
        with self._lock:
            self._trim_samples(now)
            samples = list(self.samples)
            pending = list(self._pending.values())
            connected = self.connected
            reconnects = self.reconnects
            publish_errors = self.publish_errors


        all_samples = samples + [Sample(s.published_at, failed=True) for s in pending]
        total = len(all_samples)
        acked = [s for s in all_samples if s.acked_at is not None and not s.failed]
        failed = [s for s in all_samples if s.failed or s.acked_at is None]

        latencies = [
            s.acked_at - s.published_at
            for s in acked
            if s.acked_at is not None
        ]

        delivered = len(acked)
        lost = len(failed)
        loss_ratio = lost / total if total > 0 else 0.0

        return {
            "success": 1.0 if total > 0 and len(failed) == 0 else 0.0,
            "offered_messages": float(total),
            "delivered_messages": float(delivered),
            "lost_messages": float(lost),
            "loss_ratio": max(0.0, min(loss_ratio, 1.0)),
            "latency_avg_seconds": statistics.mean(latencies) if latencies else 0.0,
            "latency_max_seconds": max(latencies) if latencies else 0.0,
            "latency_p99_seconds": self._percentile(latencies, 0.99) if latencies else 0.0,
            "connected": 1.0 if connected else 0.0,
            "reconnects_total": float(reconnects),
            "publish_errors_total": float(publish_errors),
            "timestamp_seconds": now,
        }

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(values)
        k = (len(sorted_values) - 1) * percentile
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_values[int(k)]
        return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)

    def _write_metrics(self) -> None:
        now = self.wall_clock()
        values = self._aggregate(now)
        labels = (
            f'broker="{self.broker_host}",port="{self.broker_port}",'
            f'topic="{self.topic}",qos="{self.qos}"'
        )
        lines = [
            "# HELP capstone_mqtt_probe_up Whether the MQTT probe service is running.",
            "# TYPE capstone_mqtt_probe_up gauge",
            f"capstone_mqtt_probe_up{{{labels}}} {1 if self.running else 0}",
            "# HELP capstone_mqtt_probe_connected Whether the MQTT probe is connected to the broker.",
            "# TYPE capstone_mqtt_probe_connected gauge",
            f"capstone_mqtt_probe_connected{{{labels}}} {values['connected']}",
            "# HELP capstone_mqtt_probe_messages_offered_total Probe messages expected in the window.",
            "# TYPE capstone_mqtt_probe_messages_offered_total gauge",
            f"capstone_mqtt_probe_messages_offered_total{{{labels}}} {values['offered_messages']}",
            "# HELP capstone_mqtt_probe_messages_delivered_total Probe messages delivered/acked in the window.",
            "# TYPE capstone_mqtt_probe_messages_delivered_total gauge",
            f"capstone_mqtt_probe_messages_delivered_total{{{labels}}} {values['delivered_messages']}",
            "# HELP capstone_mqtt_probe_messages_lost_total Probe messages lost in the window.",
            "# TYPE capstone_mqtt_probe_messages_lost_total gauge",
            f"capstone_mqtt_probe_messages_lost_total{{{labels}}} {values['lost_messages']}",
            "# HELP capstone_mqtt_probe_loss_ratio Ratio of probe messages lost in the window.",
            "# TYPE capstone_mqtt_probe_loss_ratio gauge",
            f"capstone_mqtt_probe_loss_ratio{{{labels}}} {values['loss_ratio']}",
            "# HELP capstone_mqtt_probe_latency_seconds_average Average probe publish-to-ack latency.",
            "# TYPE capstone_mqtt_probe_latency_seconds_average gauge",
            f"capstone_mqtt_probe_latency_seconds_average{{{labels}}} {values['latency_avg_seconds']}",
            "# HELP capstone_mqtt_probe_latency_seconds_max Maximum probe publish-to-ack latency.",
            "# TYPE capstone_mqtt_probe_latency_seconds_max gauge",
            f"capstone_mqtt_probe_latency_seconds_max{{{labels}}} {values['latency_max_seconds']}",
            "# HELP capstone_mqtt_probe_latency_seconds_p99 99th percentile probe publish-to-ack latency.",
            "# TYPE capstone_mqtt_probe_latency_seconds_p99 gauge",
            f"capstone_mqtt_probe_latency_seconds_p99{{{labels}}} {values['latency_p99_seconds']}",
            "# HELP capstone_mqtt_probe_reconnects_total Cumulative MQTT reconnects.",
            "# TYPE capstone_mqtt_probe_reconnects_total counter",
            f"capstone_mqtt_probe_reconnects_total{{{labels}}} {values['reconnects_total']}",
            "# HELP capstone_mqtt_probe_publish_errors_total Cumulative publish errors.",
            "# TYPE capstone_mqtt_probe_publish_errors_total counter",
            f"capstone_mqtt_probe_publish_errors_total{{{labels}}} {values['publish_errors_total']}",
            "# HELP capstone_mqtt_probe_success Whether the latest probe window succeeded without loss.",
            "# TYPE capstone_mqtt_probe_success gauge",
            f"capstone_mqtt_probe_success{{{labels}}} {values['success']}",
            "# HELP capstone_mqtt_probe_timestamp_seconds Unix timestamp when metrics were generated.",
            "# TYPE capstone_mqtt_probe_timestamp_seconds gauge",
            f"capstone_mqtt_probe_timestamp_seconds{{{labels}}} {values['timestamp_seconds']}",
        ]
        atomic_write(self.output_path, "\n".join(lines) + "\n")

    def _save_state(self) -> None:
        with self._lock:
            state = {
                "reconnects_total": self.reconnects,
                "publish_errors_total": self.publish_errors,
            }
        atomic_write(self.state_path, json.dumps(state, sort_keys=True), 0o600)

    def _restore_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                return
            with self._lock:
                self.reconnects = max(0, int(state.get("reconnects_total", 0)))
                self.publish_errors = max(0, int(state.get("publish_errors_total", 0)))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
            pass

    def run(self) -> int:
        if self.mqtt is None:
            print("paho-mqtt is not installed; cannot run MQTT probe", flush=True)
            return 1

        import signal
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self._restore_state()
        self.running = True
        self._stop_event.clear()

        metrics_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        metrics_thread.start()

        client = self._make_client()
        try:
            client.connect_async(self.broker_host, self.broker_port, keepalive=30)
            client.loop_start()

            interval = 1.0 / self.rate_per_second
            sequence = 0
            next_publish = self.wall_clock()

            while self.running:
                now = self.wall_clock()
                if now < next_publish:
                    self._stop_event.wait(max(0.0, next_publish - now))
                    continue
                self._publish_once(client, sequence)
                sequence += 1
                next_publish += interval
        finally:
            self.stop()
            try:
                client.disconnect()
            except Exception:
                pass
            client.loop_stop()
            metrics_thread.join(timeout=self.metrics_interval + 1.0)
            self._flush()

            try:
                self.output_path.unlink()
            except FileNotFoundError:
                pass
        return 0


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capstone MQTT QoS probe")
    parser.add_argument("--broker", required=True, help="MQTT broker hostname / IP")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--topic", default="capstone/probe/qos", help="MQTT topic to publish to")
    parser.add_argument("--client-id", default="capstone-mqtt-probe", help="MQTT client id")
    parser.add_argument("--rate", type=float, default=10.0, help="Probe messages per second")
    parser.add_argument("--payload-size", type=int, default=256, help="Probe payload size in bytes")
    parser.add_argument("--qos", type=int, default=0, choices=[0, 1, 2], help="MQTT QoS level")
    parser.add_argument("--output", type=Path, required=True, help="Prometheus textfile output path")
    parser.add_argument("--state", type=Path, required=True, help="Persistent state file path")
    parser.add_argument("--metrics-interval", type=float, default=15.0, help="Seconds between metric flushes")
    parser.add_argument("--window", type=float, default=60.0, help="Sliding window for loss/latency stats")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    probe = MqttProbe(
        broker_host=args.broker,
        broker_port=args.port,
        topic=args.topic,
        client_id=args.client_id,
        rate_per_second=args.rate,
        payload_size=args.payload_size,
        qos=args.qos,
        output_path=args.output,
        state_path=args.state,
        metrics_interval=args.metrics_interval,
        window_seconds=args.window,
    )
    return probe.run()


if __name__ == "__main__":
    raise SystemExit(main())
