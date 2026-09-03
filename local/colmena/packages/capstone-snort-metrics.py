#!/usr/bin/env python3

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            return state
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {
        "files": {},
        "processed_packets_total": 0.0,
        "blocked_packets_total": 0.0,
        "daq_dropped_packets_total": 0.0,
        "alerts_total": 0.0,
        "parser_errors_total": 0.0,
        "last_perf_timestamp": 0.0,
    }


def numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    return None


def find_key_values(value: Any, key_names: set[str]) -> list[float]:
    values: list[float] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower().replace("_", ".")
            if normalized in key_names:
                parsed = numeric(child)
                if parsed is not None:
                    values.append(parsed)
            values.extend(find_key_values(child, key_names))
    elif isinstance(value, list):
        for child in value:
            values.extend(find_key_values(child, key_names))
    return values


def find_module_peg(value: Any, module: str, peg: str) -> list[float]:
    values: list[float] = []
    if isinstance(value, dict):
        module_name = value.get("module", value.get("name"))
        if isinstance(module_name, str) and module_name.lower() == module:
            values.extend(find_key_values(value, {peg, f"{module}.{peg}"}))

        for key, child in value.items():
            if key.lower() == module:
                values.extend(find_key_values(child, {peg, f"{module}.{peg}"}))
            values.extend(find_module_peg(child, module, peg))
    elif isinstance(value, list):
        for child in value:
            values.extend(find_module_peg(child, module, peg))
    return values


def extract_peg(record: dict[str, Any], module: str, peg: str) -> float:
    direct = find_key_values(record, {f"{module}.{peg}"})
    scoped = find_module_peg(record, module, peg)
    values = direct if direct else scoped
    return sum(values)


def read_new_lines(path: Path, file_state: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    stat = path.stat()
    inode = int(stat.st_ino)
    offset = int(file_state.get("offset", 0))
    partial = str(file_state.get("partial", ""))
    if int(file_state.get("inode", inode)) != inode or stat.st_size < offset:
        offset = 0
        partial = ""

    MAX_CHUNK = 1048576

    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_CHUNK)
        new_offset = handle.tell()

    text = partial + chunk.decode("utf-8", errors="replace")
    complete = text.endswith("\n")
    lines = text.splitlines()
    if not complete and lines:
        new_partial = lines.pop()
    else:
        new_partial = ""

    return lines, {"inode": inode, "offset": new_offset, "partial": new_partial}


def extract_json_objects(text: str) -> tuple[list[str], str]:
    objects: list[str] = []
    object_start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, character in enumerate(text):
        if object_start is None:
            if character == "{":
                object_start = index
                depth = 1
            continue

        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                objects.append(text[object_start : index + 1])
                object_start = None

    partial = text[object_start:] if object_start is not None else ""
    return objects, partial


def read_new_json_objects(path: Path, file_state: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    stat = path.stat()
    inode = int(stat.st_ino)
    offset = int(file_state.get("offset", 0))
    partial = str(file_state.get("partial", ""))
    if int(file_state.get("inode", inode)) != inode or stat.st_size < offset:
        offset = 0
        partial = ""

    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(1048576)
        new_offset = handle.tell()

    objects, next_partial = extract_json_objects(partial + chunk.decode("utf-8", errors="replace"))
    return objects, {"inode": inode, "offset": new_offset, "partial": next_partial}


def collect_perf(pattern: str, state: dict[str, Any], now: float) -> bool:
    found_valid = False
    for filename in sorted(glob.glob(pattern)):
        path = Path(filename)
        key = f"perf:{path}"
        try:
            objects, next_state = read_new_json_objects(path, state["files"].get(key, {}))
        except OSError:
            state["parser_errors_total"] += 1
            continue
        state["files"][key] = next_state

        for raw_object in objects:
            try:
                record = json.loads(raw_object)
                if not isinstance(record, dict):
                    raise ValueError("perf record is not an object")
                state["processed_packets_total"] += extract_peg(record, "daq", "analyzed")
                state["blocked_packets_total"] += extract_peg(record, "daq", "block")
                state["blocked_packets_total"] += extract_peg(record, "daq", "blocks")
                state["daq_dropped_packets_total"] += extract_peg(record, "daq", "dropped")
                found_valid = True
            except (json.JSONDecodeError, ValueError, TypeError):
                state["parser_errors_total"] += 1

    if found_valid:
        state["last_perf_timestamp"] = now
    return found_valid


def collect_alerts(pattern: str, state: dict[str, Any]) -> None:




    MAX_ALERT_LINES_PER_RUN = 8_000_000
    for filename in sorted(glob.glob(pattern)):
        path = Path(filename)
        key = f"alert:{path}"
        lines_read = 0
        while True:
            try:
                lines, next_state = read_new_lines(path, state["files"].get(key, {}))
            except OSError:
                state["parser_errors_total"] += 1
                break
            state["files"][key] = next_state
            lines_read += len(lines)
            for line in lines:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("alert record is not an object")
                    state["alerts_total"] += 1
                    if str(record.get("action", "")).lower() in {"block", "drop"}:
                        state["blocked_packets_total"] += 1
                except (json.JSONDecodeError, ValueError):
                    state["parser_errors_total"] += 1
            if lines_read >= MAX_ALERT_LINES_PER_RUN:
                break
            try:
                if path.stat().st_size <= int(state["files"][key].get("offset", 0)):
                    break
            except OSError:
                break


def command_succeeds(command: list[str], contains: str | None = None) -> bool:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    return contains is None or contains in completed.stdout


def service_active(systemctl: str, service_name: str) -> bool:
    return command_succeeds([systemctl, "is-active", "--quiet", service_name])


def daq_available(snort: str, daq_dir: str, daq_kind: str) -> bool:
    return command_succeeds([snort, "--daq-dir", daq_dir, "--daq-list"], daq_kind)


def queue_present(nft: str) -> bool:
    try:
        completed = subprocess.run(
            [nft, "list", "table", "inet", "capstone_inline"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    queue_zero_rules = completed.stdout.count("queue num 0") + completed.stdout.count("queue flags bypass to 0")
    return queue_zero_rules >= 2


def get_nft_queued_total(nft: str) -> int:
    try:
        completed = subprocess.run(
            [nft, "-j", "list", "table", "inet", "capstone_inline"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if completed.returncode != 0:
        return 0
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return 0
    total = 0
    for entry in data.get("nftables", []):
        if "rule" not in entry:
            continue
        rule = entry["rule"]
        for expr in rule.get("expr", []):
            if "counter" in expr:
                total += int(expr["counter"].get("packets", 0))
    return total


def current_mode(path: Path | None) -> str:
    if path is None:
        return "normal"
    try:
        mode = path.read_text(encoding="utf-8").strip()
        return mode if mode in {"normal", "drop-test"} else "invalid"
    except OSError:
        return "normal"


def parse_labels(text: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    if not text:
        return labels
    for pair in text.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        labels[key.strip()] = value.strip()
    return labels


def labels(base: dict[str, str], extra: dict[str, str] | None = None) -> str:
    dimensions = dict(base)
    if extra:
        dimensions.update(extra)
    return "{" + ",".join(f'{key}="{value}"' for key, value in dimensions.items()) + "}"


def render_metrics(
    metric_prefix: str,
    metric_labels: dict[str, str],
    state: dict[str, Any],
    readiness: dict[str, float],
    mode: str,
    now: float,
    freshness: int,
) -> str:
    last_perf = float(state.get("last_perf_timestamp", 0.0))
    available = float(last_perf > 0 and now - last_perf <= freshness)

    metrics: list[tuple[str, str, str, float, dict[str, str] | None]] = [
        (f"{metric_prefix}_up", "Whether the Snort service is active.", "gauge", readiness["up"], None),
        (f"{metric_prefix}_metrics_available", "Whether fresh Snort perf_monitor data is available.", "gauge", available, None),
        (f"{metric_prefix}_daq_available", f"Whether the installed Snort build exposes the requested DAQ module.", "gauge", readiness["daq"], None),
        (f"{metric_prefix}_alerts_total", "Alerts emitted by the current Capstone Snort deployment.", "counter", state["alerts_total"], None),
        (f"{metric_prefix}_processed_packets_total", "Packets analyzed by Snort.", "counter", state["processed_packets_total"], None),
        (f"{metric_prefix}_dropped_packets_total", "Block or drop verdict events emitted by Snort IPS rules.", "counter", state["blocked_packets_total"], None),
        (f"{metric_prefix}_daq_dropped_packets_total", "Packets dropped by the DAQ acquisition path.", "counter", state["daq_dropped_packets_total"], None),
        (f"{metric_prefix}_parser_errors_total", "Snort metric parser errors.", "counter", state["parser_errors_total"], None),
        (f"{metric_prefix}_metrics_timestamp_seconds", "Timestamp of the latest successfully parsed perf_monitor record.", "gauge", last_perf, None),
    ]

    if readiness.get("queue") is not None:
        metrics.insert(
            3,
            (
                f"{metric_prefix}_queue_rule_present",
                "Whether both Capstone NFQUEUE forwarding rules are present.",
                "gauge",
                readiness["queue"],
                None,
            ),
        )

    if mode:
        metrics.append(
            (
                f"{metric_prefix}_mode_info",
                "Current Capstone Snort policy mode.",
                "gauge",
                1.0,
                {"mode": mode},
            )
        )

    lines: list[str] = []
    for name, help_text, metric_type, value, extra in metrics:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        lines.append(f"{name}{labels(metric_labels, extra)} {format(float(value), '.17g')}")
    return "\n".join(lines) + "\n"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perf-glob", required=True)
    parser.add_argument("--alert-glob", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode-file", type=Path, default=None)
    parser.add_argument("--snort", required=True)
    parser.add_argument("--daq-dir", required=True)
    parser.add_argument("--daq-kind", default="nfq", help="DAQ module to verify, e.g. nfq or pcap")
    parser.add_argument("--service-name", default="snort-inline.service")
    parser.add_argument("--systemctl", default="systemctl")
    parser.add_argument("--nft", default="nft")
    parser.add_argument("--metric-prefix", default="capstone_snort")
    parser.add_argument("--metric-labels", default="vnf=snort-inline", help="Comma-separated key=value labels")
    parser.add_argument("--skip-nft-check", action="store_true", help="Skip NFQUEUE nftables readiness check")
    parser.add_argument("--freshness-seconds", type=int, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    now = time.time()
    state = load_state(args.state)
    state.setdefault("files", {})
    for key in (
        "processed_packets_total",
        "blocked_packets_total",
        "daq_dropped_packets_total",
        "alerts_total",
        "parser_errors_total",
        "last_perf_timestamp",
        "nft_queued_total",
    ):
        state.setdefault(key, 0.0)

    collect_perf(args.perf_glob, state, now)
    collect_alerts(args.alert_glob, state)

    if not args.skip_nft_check:
        state["nft_queued_total"] = float(get_nft_queued_total(args.nft))



    nft_blocked = max(0.0, state["nft_queued_total"] - state["processed_packets_total"])
    state["blocked_packets_total"] = max(state["blocked_packets_total"], nft_blocked)

    readiness: dict[str, float] = {
        "up": float(service_active(args.systemctl, args.service_name)),
        "daq": float(daq_available(args.snort, args.daq_dir, args.daq_kind)),
    }
    if not args.skip_nft_check:
        readiness["queue"] = float(queue_present(args.nft))

    mode = current_mode(args.mode_file)
    metric_labels = parse_labels(args.metric_labels)

    atomic_write(args.state, json.dumps(state, sort_keys=True) + "\n", 0o600)
    atomic_write(
        args.output,
        render_metrics(
            args.metric_prefix,
            metric_labels,
            state,
            readiness,
            mode,
            now,
            args.freshness_seconds,
        ),
        0o644,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
