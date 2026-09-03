#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import signal
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None


STATE_VERSION = 2
INVENTORY_VERSION = 1


def _device(
    name: str,
    kind: str,
    room: str,
    interval: float,
    payload_bytes: int,
    qos: int = 0,
    mode: str = "periodic",
    jitter: float = 0.5,
    burst_count: int = 1,
    burst_spacing: float = 0.2,
    stream: str = "telemetry",
    profile: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "room": room,
        "qos": qos,
        "client_id": f"capstone-{name}",
        "topic": f"home/{room}/{name}/{stream}",
        "schedule": {
            "mode": mode,
            "interval_seconds": interval,
            "jitter_seconds": jitter,
            "burst_count": burst_count,
            "burst_spacing_seconds": burst_spacing,
        },
        "payload": {
            "profile": profile if profile is not None else kind,
            "target_bytes": payload_bytes,
        },
    }



_EMBEDDED_DEVICES: list[dict[str, Any]] = [
    _device("living-room-camera", "camera", "living-room", 1.20, 768, stream="status"),
    _device("front-door-camera", "camera", "entrance", 1.37, 832, stream="status"),
    _device("garage-camera", "camera", "garage", 1.54, 896, stream="status"),
    _device("nursery-camera", "camera", "nursery", 1.71, 960, stream="status"),
    _device("backyard-camera", "camera", "backyard", 1.88, 1024, stream="status"),
    _device("front-door-lock", "lock", "entrance", 31.0, 160, qos=1, mode="burst", burst_count=2, stream="events"),
    _device("back-door-lock", "lock", "backyard", 35.0, 160, qos=1, mode="burst", burst_count=2, stream="events"),
    _device("garage-entry-lock", "lock", "garage", 39.0, 176, qos=2, mode="burst", burst_count=2, stream="events"),
    _device("side-gate-lock", "lock", "side-gate", 43.0, 176, qos=1, mode="burst", burst_count=2, stream="events"),
    _device("office-cabinet-lock", "lock", "office", 47.0, 144, qos=1, mode="burst", burst_count=2, stream="events"),
    _device("hallway-motion-sensor", "motion-sensor", "hallway", 12.0, 112, qos=1, mode="burst", burst_count=3, stream="motion"),
    _device("living-room-motion-sensor", "motion-sensor", "living-room", 14.5, 112, mode="burst", burst_count=3, stream="motion"),
    _device("kitchen-motion-sensor", "motion-sensor", "kitchen", 17.0, 120, qos=1, mode="burst", burst_count=4, stream="motion"),
    _device("upstairs-landing-motion-sensor", "motion-sensor", "upstairs", 19.5, 120, mode="burst", burst_count=3, stream="motion"),
    _device("basement-motion-sensor", "motion-sensor", "basement", 22.0, 128, qos=1, mode="burst", burst_count=4, stream="motion"),
    _device("garage-motion-sensor", "motion-sensor", "garage", 24.5, 128, mode="burst", burst_count=3, stream="motion"),
    _device("backyard-motion-sensor", "motion-sensor", "backyard", 27.0, 136, qos=1, mode="burst", burst_count=5, stream="motion"),
    _device("entrance-motion-sensor", "motion-sensor", "entrance", 29.5, 136, mode="burst", burst_count=4, stream="motion"),
    _device("kitchen-temperature-sensor", "temperature-sensor", "kitchen", 7.0, 192, stream="temperature"),
    _device("bedroom-temperature-sensor", "temperature-sensor", "bedroom", 8.75, 192, qos=1, stream="temperature"),
    _device("nursery-temperature-sensor", "temperature-sensor", "nursery", 10.5, 208, stream="temperature"),
    _device("attic-temperature-sensor", "temperature-sensor", "attic", 12.25, 208, qos=1, stream="temperature"),
    _device("basement-temperature-sensor", "temperature-sensor", "basement", 14.0, 224, stream="temperature"),
    _device("garage-temperature-sensor", "temperature-sensor", "garage", 15.75, 224, qos=1, stream="temperature"),
    _device("greenhouse-temperature-sensor", "temperature-sensor", "greenhouse", 17.5, 240, stream="temperature"),
    _device("utility-temperature-sensor", "temperature-sensor", "utility", 19.25, 240, qos=1, stream="temperature"),
    _device("living-room-thermostat", "thermostat", "living-room", 4.0, 256, qos=1, stream="state"),
    _device("bedroom-thermostat", "thermostat", "bedroom", 5.1, 256, qos=1, stream="state"),
    _device("nursery-thermostat", "thermostat", "nursery", 6.2, 272, qos=1, stream="state"),
    _device("office-thermostat", "thermostat", "office", 7.3, 272, qos=1, stream="state"),
    _device("basement-thermostat", "thermostat", "basement", 8.4, 288, qos=1, stream="state"),
    _device("living-room-smart-speaker", "speaker", "living-room", 13.0, 320, mode="burst", burst_count=3, stream="events"),
    _device("kitchen-smart-speaker", "speaker", "kitchen", 18.0, 336, qos=1, mode="burst", burst_count=3, stream="events"),
    _device("bedroom-smart-speaker", "speaker", "bedroom", 23.0, 352, mode="burst", burst_count=4, stream="events"),
    _device("office-smart-speaker", "speaker", "office", 28.0, 368, qos=1, mode="burst", burst_count=4, stream="events"),
    _device("garage-door-controller", "actuator", "garage", 23.0, 224, qos=2, mode="burst", burst_count=2, stream="command"),
    _device("living-room-blind-controller", "actuator", "living-room", 30.0, 224, qos=1, mode="burst", burst_count=2, stream="command"),
    _device("bedroom-blind-controller", "actuator", "bedroom", 37.0, 240, qos=1, mode="burst", burst_count=2, stream="command"),
    _device("garden-irrigation-controller", "actuator", "garden", 44.0, 240, qos=2, mode="burst", burst_count=2, stream="command"),
    _device("attic-vent-controller", "actuator", "attic", 51.0, 256, qos=1, mode="burst", burst_count=2, stream="command"),
    _device("whole-home-energy-meter", "meter", "utility", 2.5, 288, qos=1, stream="energy"),
    _device("kitchen-circuit-energy-meter", "meter", "kitchen", 3.4, 288, stream="energy"),
    _device("hvac-energy-meter", "meter", "utility", 4.3, 304, qos=1, stream="energy"),
    _device("ev-charger-energy-meter", "meter", "garage", 5.2, 304, stream="energy"),
    _device("solar-inverter-energy-meter", "meter", "roof", 6.1, 320, qos=1, stream="energy"),
    _device("laundry-leak-sensor", "leak-sensor", "laundry", 37.0, 160, qos=1, mode="burst", burst_count=2, stream="events"),
    _device("basement-leak-sensor", "leak-sensor", "basement", 41.0, 160, qos=1, mode="burst", burst_count=2, stream="events"),
    _device("kitchen-smoke-sensor", "smoke-sensor", "kitchen", 45.0, 176, qos=2, mode="burst", burst_count=3, stream="events"),
    _device("hallway-air-quality-sensor", "air-quality-sensor", "hallway", 11.0, 224, qos=1, stream="air-quality"),
    _device("garden-soil-moisture-sensor", "soil-moisture-sensor", "garden", 17.0, 208, qos=1, stream="soil-moisture"),
]


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
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _number(value: Any, field_name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number")
    result = float(value)
    if (positive and result <= 0) or (not positive and result < 0):
        comparison = "greater than zero" if positive else "non-negative"
        raise ValueError(f"{field_name} must be {comparison}")
    return result


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ScheduleConfig:
    mode: str
    interval_seconds: float
    jitter_seconds: float
    burst_count: int = 1
    burst_spacing_seconds: float = 0.0

    @classmethod
    def from_dict(cls, value: Any) -> "ScheduleConfig":
        if not isinstance(value, dict):
            raise ValueError("schedule must be an object")
        mode = _nonempty_string(value.get("mode"), "schedule.mode")
        if mode not in {"periodic", "burst"}:
            raise ValueError("schedule.mode must be 'periodic' or 'burst'")
        interval = _number(value.get("interval_seconds"), "schedule.interval_seconds", positive=True)
        jitter = _number(value.get("jitter_seconds"), "schedule.jitter_seconds")
        burst_count = value.get("burst_count", 1)
        if isinstance(burst_count, bool) or not isinstance(burst_count, int) or burst_count < 1:
            raise ValueError("schedule.burst_count must be a positive integer")
        spacing = _number(value.get("burst_spacing_seconds", 0), "schedule.burst_spacing_seconds")
        if jitter >= interval:
            raise ValueError("schedule.jitter_seconds must be less than interval_seconds")
        if mode == "periodic" and burst_count != 1:
            raise ValueError("periodic schedules must have burst_count 1")
        if mode == "burst" and burst_count > 1 and spacing <= 0:
            raise ValueError("burst_spacing_seconds must be greater than zero for a burst")
        if mode == "burst" and spacing * (burst_count - 1) >= interval - jitter:
            raise ValueError("a burst must fit within the shortest jittered interval")
        return cls(mode, interval, jitter, burst_count, spacing)


@dataclass(frozen=True)
class PayloadConfig:
    profile: str
    target_bytes: int

    @classmethod
    def from_dict(cls, value: Any) -> "PayloadConfig":
        if not isinstance(value, dict):
            raise ValueError("payload must be an object")
        profile = _nonempty_string(value.get("profile"), "payload.profile")
        target_bytes = value.get("target_bytes")
        if isinstance(target_bytes, bool) or not isinstance(target_bytes, int) or target_bytes <= 0:
            raise ValueError("payload.target_bytes must be a positive integer")
        return cls(profile, target_bytes)


@dataclass(frozen=True)
class DeviceConfig:
    name: str
    client_id: str
    kind: str
    room: str
    topic: str
    qos: int
    schedule: ScheduleConfig
    payload: PayloadConfig

    @classmethod
    def from_dict(cls, value: Any) -> "DeviceConfig":
        if not isinstance(value, dict):
            raise ValueError("each device must be an object")
        qos = value.get("qos")
        if isinstance(qos, bool) or not isinstance(qos, int) or qos not in {0, 1, 2}:
            raise ValueError("device.qos must be 0, 1, or 2")
        return cls(
            name=_nonempty_string(value.get("name"), "device.name"),
            client_id=_nonempty_string(value.get("client_id"), "device.client_id"),
            kind=_nonempty_string(value.get("kind"), "device.kind"),
            room=_nonempty_string(value.get("room"), "device.room"),
            topic=_nonempty_string(value.get("topic"), "device.topic"),
            qos=qos,
            schedule=ScheduleConfig.from_dict(value.get("schedule")),
            payload=PayloadConfig.from_dict(value.get("payload")),
        )


def load_device_inventory(path: Path, expected_devices: int | None = None) -> list[DeviceConfig]:
    if expected_devices is not None and (
        isinstance(expected_devices, bool) or not isinstance(expected_devices, int) or expected_devices <= 0
    ):
        raise ValueError("expected device count must be a positive integer")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load device inventory {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("version") != INVENTORY_VERSION:
        raise ValueError(f"device inventory version must be {INVENTORY_VERSION}")
    raw_devices = document.get("devices")
    if not isinstance(raw_devices, list) or not raw_devices:
        raise ValueError("device inventory must contain a non-empty devices array")
    devices = [DeviceConfig.from_dict(value) for value in raw_devices]
    for attribute in ("name", "client_id", "topic"):
        values = [getattr(device, attribute) for device in devices]
        if len(values) != len(set(values)):
            raise ValueError(f"device {attribute} values must be unique")
    if expected_devices is not None and len(devices) != expected_devices:
        raise ValueError(f"expected {expected_devices} devices, found {len(devices)}")
    return devices


def prometheus_escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def embedded_devices() -> list[DeviceConfig]:
    return [DeviceConfig.from_dict(value) for value in _EMBEDDED_DEVICES]


def stable_jitter(device: DeviceConfig) -> float:
    if device.schedule.jitter_seconds == 0:
        return 0.0
    digest = hashlib.sha256(device.client_id.encode("utf-8")).digest()
    fraction = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
    return (fraction * 2.0 - 1.0) * device.schedule.jitter_seconds


def _profile_fields(kind: str, profile: str, sequence: int) -> dict[str, object]:
    normalized = kind.lower()
    if normalized == "camera":
        return {"motion_detected": sequence % 5 == 0, "frame_rate": 24, "bitrate_kbps": 1800}
    if normalized == "lock":
        return {"locked": sequence % 17 != 0, "battery_percent": 91 - sequence % 12}
    if normalized == "motion-sensor":
        return {"motion_detected": sequence % 4 == 0, "confidence": round(0.72 + (sequence % 20) / 100, 2)}
    if normalized == "temperature-sensor":
        return {"temperature_celsius": round(20.0 + (sequence % 30) / 10, 1), "humidity_percent": 42 + sequence % 9}
    if normalized == "thermostat":
        return {"temperature_celsius": round(19.5 + (sequence % 25) / 10, 1), "setpoint_celsius": 22.0, "heating": sequence % 3 == 0}
    if normalized == "speaker":
        return {"playing": sequence % 7 != 0, "volume_percent": 30 + sequence % 40, "track": f"stream-{sequence % 6}"}
    if normalized == "actuator":
        return {"active": sequence % 2 == 0, "position_percent": sequence % 101}
    if normalized == "meter":
        return {"power_watts": round(250 + (sequence % 80) * 2.5, 1), "energy_kwh": round(1000 + sequence * 0.01, 2)}
    if normalized == "leak-sensor":
        return {"leak_detected": sequence % 101 == 0, "battery_percent": 88 - sequence % 8}
    if normalized == "smoke-sensor":
        return {"smoke_detected": sequence % 211 == 0, "particulates_ppm": round(0.01 + (sequence % 8) / 100, 2)}
    if normalized == "air-quality-sensor":
        return {"co2_ppm": 410 + sequence % 190, "voc_index": 30 + sequence % 25, "pm25_ug_m3": 5 + sequence % 12}
    if normalized == "soil-moisture-sensor":
        return {"moisture_percent": 35 + sequence % 30, "temperature_celsius": round(17 + (sequence % 20) / 10, 1)}
    return {"profile": profile, "value": round((sequence * 17 % 1000) / 10, 1), "status": "nominal"}


def build_payload(device: DeviceConfig, sequence: int, timestamp: float) -> bytes:
    payload: dict[str, object] = {
        "device": device.name,
        "kind": device.kind,
        "room": device.room,
        "sequence": sequence,
        "timestamp": datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload.update(_profile_fields(device.kind, device.payload.profile, sequence))
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) < device.payload.target_bytes:
        payload["padding"] = ""
        base = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload["padding"] = "x" * max(0, device.payload.target_bytes - len(base))
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return encoded


@dataclass
class DeviceState:
    messages_sent: int = 0
    bytes_sent: int = 0
    publish_errors: int = 0
    reconnects: int = 0
    sequence: int = 0
    last_publish_timestamp: float = 0.0
    connected: bool = False
    ever_connected: bool = False
    pending: dict[int, tuple[int, float]] = field(default_factory=dict)
    next_publish: float = 0.0
    burst_index: int = 0
    latency_sum: float = 0.0
    latency_count: int = 0
    latency_max: float = 0.0
    latency_bucket: dict[str, int] = field(default_factory=lambda: {
        "0.005": 0,
        "0.01": 0,
        "0.025": 0,
        "0.05": 0,
        "0.1": 0,
        "0.25": 0,
        "0.5": 0,
        "1.0": 0,
        "+Inf": 0,
    })


class MqttTrafficGenerator:

    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        devices: list[DeviceConfig],
        output_path: Path,
        state_path: Path,
        metrics_interval: float,
        expected_devices: int | None = None,
        mqtt_module: Any = None,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not devices:
            raise ValueError("at least one device is required")
        if expected_devices is not None and (
            isinstance(expected_devices, bool) or not isinstance(expected_devices, int) or expected_devices <= 0
        ):
            raise ValueError("expected device count must be a positive integer")
        if expected_devices is not None and len(devices) != expected_devices:
            raise ValueError(f"expected {expected_devices} devices, found {len(devices)}")
        if metrics_interval <= 0:
            raise ValueError("metrics_interval must be greater than zero")
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.devices = devices
        self.output_path = output_path
        self.state_path = state_path
        self.metrics_interval = metrics_interval
        self.mqtt = mqtt if mqtt_module is None else mqtt_module
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock
        self.states = {device.name: DeviceState() for device in devices}
        self.clients: dict[str, Any] = {}
        self.legacy_messages = 0
        self.legacy_bytes = 0
        self.running = False
        self.last_error = ""
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

    def _handle_signal(self, signum: int, frame: object) -> None:
        del signum, frame
        self.stop()

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()

    def _on_connect(self, device: DeviceConfig, reason_code: Any) -> None:
        failed = getattr(reason_code, "is_failure", reason_code != 0)
        with self._lock:
            state = self.states[device.name]
            if failed:
                state.connected = False
                self.last_error = f"MQTT connect failed for {device.name}: {reason_code}"
                return
            if state.ever_connected and not state.connected:
                state.reconnects += 1
            state.connected = True
            state.ever_connected = True
            self.last_error = ""

    def _on_disconnect(self, device: DeviceConfig, reason_code: Any) -> None:
        with self._lock:
            self.states[device.name].connected = False
            if reason_code not in (0, None):
                self.last_error = f"MQTT disconnect for {device.name}: {reason_code}"

    def _on_publish(self, device: DeviceConfig, mid: int) -> None:
        with self._lock:
            state = self.states[device.name]
            pending = state.pending.pop(mid, None)
            if pending is None:
                return
            payload_bytes, published_at = pending
            latency = self.wall_clock() - published_at
            state.messages_sent += 1
            state.bytes_sent += payload_bytes
            state.last_publish_timestamp = published_at
            state.latency_sum += latency
            state.latency_count += 1
            if latency > state.latency_max:
                state.latency_max = latency
            self._record_latency_bucket(state, latency)

    @staticmethod
    def _record_latency_bucket(state: DeviceState, latency: float) -> None:
        thresholds = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
        target_index = None
        for index, threshold in enumerate(thresholds):
            if latency <= threshold:
                target_index = index
                break
        if target_index is None:
            state.latency_bucket["+Inf"] += 1
        else:
            for index in range(target_index + 1):
                state.latency_bucket[str(thresholds[index])] += 1

    def _make_client(self, device: DeviceConfig) -> Any:
        client = self.mqtt.Client(
            client_id=device.client_id,
            callback_api_version=self.mqtt.CallbackAPIVersion.VERSION2,
            protocol=self.mqtt.MQTTv311,
        )
        client.on_connect = lambda client, userdata, flags, reason_code, properties: self._on_connect(device, reason_code)
        client.on_disconnect = lambda client, userdata, flags, reason_code, properties: self._on_disconnect(device, reason_code)
        client.on_publish = lambda client, userdata, mid, reason_code, properties: self._on_publish(device, mid)
        return client

    def _initialize_schedules(self, now: float) -> None:
        with self._lock:
            for device in self.devices:
                self.states[device.name].next_publish = now + max(
                    0.001, device.schedule.interval_seconds + stable_jitter(device)
                )

    def _advance_schedule(self, device: DeviceConfig, scheduled_at: float) -> None:
        state = self.states[device.name]
        schedule = device.schedule
        if schedule.mode == "burst" and state.burst_index + 1 < schedule.burst_count:
            state.burst_index += 1
            state.next_publish = scheduled_at + schedule.burst_spacing_seconds
        else:
            elapsed_burst = state.burst_index * schedule.burst_spacing_seconds
            state.burst_index = 0
            state.next_publish = scheduled_at + max(
                0.001, schedule.interval_seconds + stable_jitter(device) - elapsed_burst
            )

    def publish_due(self, now: float | None = None) -> int:
        current = self.monotonic_clock() if now is None else now
        published = 0
        for device in self.devices:
            with self._lock:
                state = self.states[device.name]
                if not state.connected or current < state.next_publish:
                    continue
                scheduled_at = state.next_publish
            if self._publish_device(device):
                published += 1
            with self._lock:
                self._advance_schedule(device, scheduled_at)
        return published

    def _publish_device(self, device: DeviceConfig) -> bool:
        with self._lock:
            state = self.states[device.name]
            timestamp = self.wall_clock()
            payload = build_payload(device, state.sequence, timestamp)
            try:
                result = self.clients[device.name].publish(device.topic, payload, qos=device.qos)
            except Exception as exc:
                state.publish_errors += 1
                self.last_error = f"publish error for {device.name}: {exc}"
                return False
            success_code = getattr(self.mqtt, "MQTT_ERR_SUCCESS", 0)
            if getattr(result, "rc", success_code) != success_code:
                state.publish_errors += 1
                self.last_error = f"publish error for {device.name}: rc={result.rc}"
                return False
            state.pending[result.mid] = (len(payload), timestamp)
            state.sequence += 1
            return True

    def _metrics_loop(self) -> None:
        while not self._stop_event.wait(self.metrics_interval):
            self._flush()

    def _flush(self) -> None:
        self._write_metrics()
        self._save_state()

    def _aggregate_labels(self) -> str:
        return f'broker="{prometheus_escape(self.broker_host)}",port="{self.broker_port}"'

    def _device_labels(self, device: DeviceConfig) -> str:
        values = {
            "device": device.name,
            "client_id": device.client_id,
            "kind": device.kind,
            "room": device.room,
            "topic": device.topic,
            "qos": device.qos,
            "broker": self.broker_host,
            "port": self.broker_port,
        }
        return ",".join(f'{key}="{prometheus_escape(value)}"' for key, value in values.items())

    def _write_metrics(self) -> None:
        with self._lock:
            snapshots = {
                name: DeviceState(
                    messages_sent=state.messages_sent,
                    bytes_sent=state.bytes_sent,
                    publish_errors=state.publish_errors,
                    reconnects=state.reconnects,
                    sequence=state.sequence,
                    last_publish_timestamp=state.last_publish_timestamp,
                    connected=state.connected,
                    latency_sum=state.latency_sum,
                    latency_count=state.latency_count,
                    latency_max=state.latency_max,
                    latency_bucket=dict(state.latency_bucket),
                )
                for name, state in self.states.items()
            }
            messages = self.legacy_messages + sum(state.messages_sent for state in snapshots.values())
            byte_count = self.legacy_bytes + sum(state.bytes_sent for state in snapshots.values())
            connected = sum(state.connected for state in snapshots.values())
            is_up = self.running
            total_latency_sum = sum(state.latency_sum for state in snapshots.values())
            total_latency_count = sum(state.latency_count for state in snapshots.values())
            total_latency_max = max(
                (state.latency_max for state in snapshots.values() if state.latency_count > 0),
                default=0.0,
            )
            aggregate_bucket: dict[str, int] = {
                "0.005": 0,
                "0.01": 0,
                "0.025": 0,
                "0.05": 0,
                "0.1": 0,
                "0.25": 0,
                "0.5": 0,
                "1.0": 0,
                "+Inf": 0,
            }
            for state in snapshots.values():
                for key, value in state.latency_bucket.items():
                    aggregate_bucket[key] += value
            aggregate_bucket["+Inf"] = total_latency_count

        labels = self._aggregate_labels()
        lines = [
            "# HELP capstone_mqtt_up Whether the MQTT traffic generator service is running.",
            "# TYPE capstone_mqtt_up gauge",
            f"capstone_mqtt_up{{{labels}}} {1 if is_up else 0}",
            "# HELP capstone_mqtt_connected Whether all configured clients are connected to the MQTT broker.",
            "# TYPE capstone_mqtt_connected gauge",
            f"capstone_mqtt_connected{{{labels}}} {1 if connected == len(self.devices) else 0}",
            "# HELP capstone_mqtt_messages_total MQTT PUBLISH messages acknowledged.",
            "# TYPE capstone_mqtt_messages_total counter",
            f"capstone_mqtt_messages_total{{{labels}}} {messages}",
            "# HELP capstone_mqtt_bytes_total MQTT payload bytes acknowledged.",
            "# TYPE capstone_mqtt_bytes_total counter",
            f"capstone_mqtt_bytes_total{{{labels}}} {byte_count}",
            "# HELP capstone_mqtt_configured_devices Number of configured MQTT devices.",
            "# TYPE capstone_mqtt_configured_devices gauge",
            f"capstone_mqtt_configured_devices{{{labels}}} {len(self.devices)}",
            "# HELP capstone_mqtt_connected_devices Number of connected MQTT devices.",
            "# TYPE capstone_mqtt_connected_devices gauge",
            f"capstone_mqtt_connected_devices{{{labels}}} {connected}",
            "# HELP capstone_mqtt_publish_latency_seconds_max Maximum publish-to-ack latency across all devices.",
            "# TYPE capstone_mqtt_publish_latency_seconds_max gauge",
            f"capstone_mqtt_publish_latency_seconds_max{{{labels}}} {total_latency_max}",
            "# HELP capstone_mqtt_publish_latency_seconds Histogram of publish-to-ack latency.",
            "# TYPE capstone_mqtt_publish_latency_seconds histogram",
        ]
        for bucket, count in aggregate_bucket.items():
            le_label = f'le="{bucket}"'
            lines.append(f"capstone_mqtt_publish_latency_seconds_bucket{{{labels},{le_label}}} {count}")
        lines.append(f"capstone_mqtt_publish_latency_seconds_sum{{{labels}}} {total_latency_sum}")
        lines.append(f"capstone_mqtt_publish_latency_seconds_count{{{labels}}} {total_latency_count}")
        lines.extend([
            "# HELP capstone_mqtt_metrics_timestamp_seconds Unix timestamp when these metrics were generated.",
            "# TYPE capstone_mqtt_metrics_timestamp_seconds gauge",
            f"capstone_mqtt_metrics_timestamp_seconds{{{labels}}} {self.wall_clock()}",
            "# HELP capstone_mqtt_device_info Static information about a configured MQTT device.",
            "# TYPE capstone_mqtt_device_info gauge",
        ])
        for device in self.devices:
            lines.append(f"capstone_mqtt_device_info{{{self._device_labels(device)}}} 1")
        metric_definitions = (
            ("connected", "gauge", "Whether this MQTT device is connected."),
            ("messages_total", "counter", "MQTT messages acknowledged for this device."),
            ("bytes_total", "counter", "MQTT payload bytes acknowledged for this device."),
            ("publish_errors_total", "counter", "MQTT publish errors for this device."),
            ("reconnects_total", "counter", "Successful MQTT reconnects for this device."),
            ("last_publish_timestamp_seconds", "gauge", "Unix timestamp of this device's latest acknowledged publish."),
            ("target_interval_seconds", "gauge", "Configured interval between publish cycles for this device."),
            ("target_payload_bytes", "gauge", "Configured target payload size for this device."),
            ("publish_latency_seconds_max", "gauge", "Maximum publish-to-ack latency for this device."),
            ("publish_latency_seconds_avg", "gauge", "Average publish-to-ack latency for this device."),
        )
        for suffix, metric_type, help_text in metric_definitions:
            lines.extend([
                f"# HELP capstone_mqtt_device_{suffix} {help_text}",
                f"# TYPE capstone_mqtt_device_{suffix} {metric_type}",
            ])
            for device in self.devices:
                state = snapshots[device.name]
                value = {
                    "connected": int(state.connected),
                    "messages_total": state.messages_sent,
                    "bytes_total": state.bytes_sent,
                    "publish_errors_total": state.publish_errors,
                    "reconnects_total": state.reconnects,
                    "last_publish_timestamp_seconds": state.last_publish_timestamp,
                    "target_interval_seconds": device.schedule.interval_seconds,
                    "target_payload_bytes": device.payload.target_bytes,
                    "publish_latency_seconds_max": state.latency_max,
                    "publish_latency_seconds_avg": (
                        state.latency_sum / state.latency_count if state.latency_count > 0 else 0.0
                    ),
                }[suffix]
                lines.append(f"capstone_mqtt_device_{suffix}{{{self._device_labels(device)}}} {value}")
        atomic_write(self.output_path, "\n".join(lines) + "\n")

    def _save_state(self) -> None:
        with self._lock:
            state = {
                "version": STATE_VERSION,
                "legacy": {"messages_sent": self.legacy_messages, "bytes_sent": self.legacy_bytes},
                "devices": {
                    name: {
                        "messages_sent": value.messages_sent,
                        "bytes_sent": value.bytes_sent,
                        "publish_errors": value.publish_errors,
                        "reconnects": value.reconnects,
                        "sequence": value.sequence,
                        "last_publish_timestamp": value.last_publish_timestamp,
                        "latency_sum": value.latency_sum,
                        "latency_count": value.latency_count,
                        "latency_max": value.latency_max,
                        "latency_bucket": value.latency_bucket,
                    }
                    for name, value in self.states.items()
                },
            }
        atomic_write(self.state_path, json.dumps(state, sort_keys=True), 0o600)

    @staticmethod
    def _saved_number(value: Any, default: int | float = 0) -> int | float:
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else default

    def _restore_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        if not isinstance(state, dict):
            return
        with self._lock:
            if "version" not in state and ("messages_sent" in state or "bytes_sent" in state):
                self.legacy_messages = int(self._saved_number(state.get("messages_sent")))
                self.legacy_bytes = int(self._saved_number(state.get("bytes_sent")))
                return
            legacy = state.get("legacy", {})
            if isinstance(legacy, dict):
                self.legacy_messages = int(self._saved_number(legacy.get("messages_sent")))
                self.legacy_bytes = int(self._saved_number(legacy.get("bytes_sent")))
            saved_devices = state.get("devices", {})
            if not isinstance(saved_devices, dict):
                return
            for name, saved in saved_devices.items():
                if name not in self.states or not isinstance(saved, dict):
                    continue
                current = self.states[name]
                current.messages_sent = int(self._saved_number(saved.get("messages_sent")))
                current.bytes_sent = int(self._saved_number(saved.get("bytes_sent")))
                current.publish_errors = int(self._saved_number(saved.get("publish_errors")))
                current.reconnects = int(self._saved_number(saved.get("reconnects")))
                current.sequence = int(self._saved_number(saved.get("sequence")))
                current.last_publish_timestamp = float(self._saved_number(saved.get("last_publish_timestamp")))
                current.latency_sum = float(self._saved_number(saved.get("latency_sum", 0.0)))
                current.latency_count = int(self._saved_number(saved.get("latency_count", 0)))
                current.latency_max = float(self._saved_number(saved.get("latency_max", 0.0)))
                saved_bucket = saved.get("latency_bucket")
                if isinstance(saved_bucket, dict):
                    for key in current.latency_bucket:
                        value = saved_bucket.get(key)
                        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                            current.latency_bucket[key] = int(value)

    def run(self) -> int:
        if self.mqtt is None:
            print("paho-mqtt is not installed; cannot generate MQTT traffic", flush=True)
            return 1
        self._restore_state()
        self.running = True
        self._stop_event.clear()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        self._initialize_schedules(self.monotonic_clock())
        self._flush()
        metrics_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        metrics_thread.start()
        try:
            for device in self.devices:
                client = self._make_client(device)
                self.clients[device.name] = client
                client.connect_async(self.broker_host, self.broker_port, keepalive=30)
                client.loop_start()
            while self.running:
                self.publish_due()
                self._stop_event.wait(0.05)
        finally:
            self.stop()
            for client in self.clients.values():
                try:
                    client.disconnect()
                except Exception:
                    pass
                client.loop_stop()
            with self._lock:
                for state in self.states.values():
                    state.connected = False
            metrics_thread.join(timeout=self.metrics_interval + 1.0)
            self._flush()

            try:
                self.output_path.unlink()
            except FileNotFoundError:
                pass
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capstone multi-device MQTT traffic generator")
    parser.add_argument("--broker", required=True, help="MQTT broker hostname / IP")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--devices", type=Path, help="Optional versioned JSON device inventory; defaults to the embedded catalog")
    parser.add_argument("--expected-devices", type=int, help="Required number of devices in the inventory")
    parser.add_argument("--output", type=Path, required=True, help="Prometheus textfile output path")
    parser.add_argument("--state", type=Path, required=True, help="Persistent state file path")
    parser.add_argument("--metrics-interval", type=float, default=10.0, help="Seconds between metric flushes")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        devices = load_device_inventory(args.devices, args.expected_devices) if args.devices else embedded_devices()
        generator = MqttTrafficGenerator(
            broker_host=args.broker,
            broker_port=args.port,
            devices=devices,
            output_path=args.output,
            state_path=args.state,
            metrics_interval=args.metrics_interval,
            expected_devices=args.expected_devices,
        )
    except ValueError as exc:
        print(f"configuration error: {exc}", flush=True)
        return 2
    return generator.run()


if __name__ == "__main__":
    raise SystemExit(main())
