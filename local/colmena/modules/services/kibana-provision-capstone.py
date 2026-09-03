#!/usr/bin/env python3

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

KBN = os.environ.get("KIBANA_URL", "http://127.0.0.1:5601").rstrip("/")
KBN_USER = os.environ.get("ELASTICSEARCH_USERNAME") or os.environ.get("KIBANA_USERNAME") or ""
KBN_PASSWORD = os.environ.get("ELASTICSEARCH_PASSWORD") or os.environ.get("KIBANA_PASSWORD") or ""


def http(method: str, path: str, body: dict | None = None, timeout: int = 60):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"kbn-xsrf": "true", "Content-Type": "application/json"}
    if KBN_USER:
        token = base64.b64encode(f"{KBN_USER}:{KBN_PASSWORD}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = "Basic " + token
    req = urllib.request.Request(
        KBN + path,
        data=data,
        method=method,
        headers=headers,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def wait_kibana(retries: int = 60, sleep_s: float = 5.0) -> None:
    for i in range(retries):
        try:
            http("GET", "/api/status")
            print(f"[ok] kibana ready ({KBN})")
            return
        except Exception as e:
            print(f"[wait] kibana not ready ({i+1}/{retries}): {e}")
            time.sleep(sleep_s)
    raise SystemExit("kibana did not become ready")


def put_vis(vid: str, title: str, vis_state: dict, query: str = "") -> str:
    body = {
        "attributes": {
            "title": title,
            "description": "",
            "version": 1,
            "uiStateJSON": "{}",
            "visState": json.dumps(vis_state, separators=(",", ":")),
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps(
                    {
                        "query": {"query": query, "language": "kuery"},
                        "filter": [],
                        "indexRefName": "kibanaSavedObjectMeta.searchSourceJSON.index",
                    },
                    separators=(",", ":"),
                ),
            },
        },
        "references": [
            {
                "name": "kibanaSavedObjectMeta.searchSourceJSON.index",
                "type": "index-pattern",
                "id": "capstone-dataset",
            }
        ],
    }
    out = http("POST", f"/api/saved_objects/visualization/{vid}?overwrite=true", body)
    print(f"[vis] {out['id']}")
    return out["id"]


def put_dash(did: str, title: str, description: str, vis_ids: list[str], panels: list[dict]) -> None:
    assert len(vis_ids) == len(panels)
    body = {
        "attributes": {
            "title": title,
            "description": description,
            "hits": 0,
            "version": 1,
            "kibanaSavedObjectMeta": {
                "searchSourceJSON": json.dumps(
                    {"query": {"query": "", "language": "kuery"}, "filter": []},
                    separators=(",", ":"),
                ),
            },
            "optionsJSON": json.dumps(
                {"useMargins": True, "syncColors": False, "hidePanelTitles": False},
                separators=(",", ":"),
            ),
            "panelsJSON": json.dumps(panels, separators=(",", ":")),
        },
        "references": [
            {"name": f"panel_{i+1}", "type": "visualization", "id": vid}
            for i, vid in enumerate(vis_ids)
        ],
    }
    out = http("POST", f"/api/saved_objects/dashboard/{did}?overwrite=true", body)
    print(f"[dashboard] {out['id']} → {out['attributes']['title']} ({len(vis_ids)} panels)")


def panel(i: int, x: int, y: int, w: int, h: int) -> dict:
    return {
        "version": "7.17.27",
        "type": "visualization",
        "gridData": {"x": x, "y": y, "w": w, "h": h, "i": str(i)},
        "panelIndex": str(i),
        "embeddableConfig": {},
        "panelRefName": f"panel_{i}",
    }


def chart_params(chart_type: str, value_title: str, series_label: str, mode: str = "normal") -> dict:
    series_type = "line" if chart_type == "line" else "histogram"
    return {
        "type": chart_type,
        "grid": {"categoryLines": False},
        "categoryAxes": [
            {
                "id": "CategoryAxis-1",
                "type": "category",
                "position": "left" if chart_type == "horizontal_bar" else "bottom",
                "show": True,
                "style": {},
                "scale": {"type": "linear"},
                "labels": {"show": True, "filter": True, "truncate": 100},
                "title": {},
            }
        ],
        "valueAxes": [
            {
                "id": "ValueAxis-1",
                "name": "LeftAxis-1",
                "type": "value",
                "position": "bottom" if chart_type == "horizontal_bar" else "left",
                "show": True,
                "style": {},
                "scale": {"type": "linear", "mode": "normal"},
                "labels": {"show": True, "rotate": 0, "filter": False, "truncate": 100},
                "title": {"text": value_title},
            }
        ],
        "seriesParams": [
            {
                "show": True,
                "type": series_type,
                "mode": mode,
                "data": {"label": series_label, "id": "1"},
                "valueAxis": "ValueAxis-1",
                "drawLinesBetweenPoints": True,
                "lineWidth": 2,
                "interpolate": "linear",
                "showCircles": True,
            }
        ],
        "addTooltip": True,
        "addLegend": True,
        "legendPosition": "right",
        "times": [],
        "addTimeMarker": False,
        "labels": {"show": False},
        "thresholdLine": {"show": False, "value": 10, "width": 1, "style": "full", "color": "#E7664C"},
    }


def terms_seg(field: str, size: int = 10) -> dict:
    return {
        "id": "2",
        "enabled": True,
        "type": "terms",
        "schema": "segment",
        "params": {
            "field": field,
            "orderBy": "1",
            "order": "desc",
            "size": size,
            "otherBucket": False,
            "otherBucketLabel": "Other",
            "missingBucket": False,
            "missingBucketLabel": "Missing",
        },
    }


def terms_group(field: str, size: int = 5) -> dict:
    return {
        "id": "3",
        "enabled": True,
        "type": "terms",
        "schema": "group",
        "params": {
            "field": field,
            "orderBy": "1",
            "order": "desc",
            "size": size,
            "otherBucket": False,
            "otherBucketLabel": "Other",
            "missingBucket": False,
            "missingBucketLabel": "Missing",
        },
    }


def hist_seg(field: str, interval: float) -> dict:
    return {
        "id": "2",
        "enabled": True,
        "type": "histogram",
        "schema": "segment",
        "params": {
            "field": field,
            "interval": interval,
            "min_doc_count": 1,
            "extended_bounds": {},
        },
    }


def metric(vid: str, title: str, field: str | None = None, query: str = "", sub: str = "") -> str:
    if field:
        aggs = [{"id": "1", "enabled": True, "type": "avg", "schema": "metric", "params": {"field": field}}]
    else:
        aggs = [{"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}}]
    return put_vis(
        vid,
        title,
        {
            "title": title,
            "type": "metric",
            "params": {
                "addTooltip": True,
                "addLegend": False,
                "type": "metric",
                "metric": {
                    "percentageMode": False,
                    "useRanges": False,
                    "colorSchema": "Green to Red",
                    "metricColorMode": "None",
                    "colorsRange": [{"from": 0, "to": 10000}],
                    "labels": {"show": True},
                    "invertColors": False,
                    "style": {
                        "bgFill": "#000",
                        "bgColor": False,
                        "labelColor": False,
                        "subText": sub,
                        "fontSize": 36,
                    },
                },
            },
            "aggs": aggs,
        },
        query=query,
    )


def hbar(vid: str, title: str, field: str, query: str = "", seg: str = "vnf_profile") -> str:
    return put_vis(
        vid,
        title,
        {
            "title": title,
            "type": "horizontal_bar",
            "params": chart_params("horizontal_bar", f"avg {field}", f"avg {field}"),
            "aggs": [
                {"id": "1", "enabled": True, "type": "avg", "schema": "metric", "params": {"field": field}},
                terms_seg(seg, size=16),
            ],
        },
        query=query,
    )


def line(
    vid: str,
    title: str,
    y_field: str,
    x_field: str,
    interval: float,
    query: str = "",
    split_field: str | None = None,
) -> str:
    aggs = [
        {"id": "1", "enabled": True, "type": "avg", "schema": "metric", "params": {"field": y_field}},
        hist_seg(x_field, interval),
    ]
    if split_field:
        aggs.append(terms_group(split_field, size=8))
    return put_vis(
        vid,
        title,
        {
            "title": title,
            "type": "line",
            "params": chart_params("line", f"avg {y_field}", f"avg {y_field}"),
            "aggs": aggs,
        },
        query=query,
    )


def pie(vid: str, title: str, query: str = "") -> str:
    return put_vis(
        vid,
        title,
        {
            "title": title,
            "type": "pie",
            "params": {
                "type": "pie",
                "addTooltip": True,
                "addLegend": True,
                "legendPosition": "right",
                "isDonut": True,
                "labels": {"show": True, "values": True, "last_level": True, "truncate": 100},
            },
            "aggs": [
                {"id": "1", "enabled": True, "type": "count", "schema": "metric", "params": {}},
                terms_seg("vnf_profile", size=5),
            ],
        },
        query=query,
    )


def q_profile(p: str) -> str:
    return f'vnf_profile: "{p}"'


def layout_grid(
    n: int,
    *,
    cols: int = 2,
    start_index: int = 1,
    start_y: int = 0,
    h: int = 10,
    total_w: int = 48,
) -> list[dict]:
    w = total_w // cols
    panels = []
    for i in range(n):
        col = i % cols
        row = i // cols
        panels.append(panel(start_index + i, col * w, start_y + row * h, w, h))
    return panels


def provision_cross() -> None:
    ids = []
    ids.append(metric("x-doc-count", "Total rows", sub="all"))
    ids.append(metric("x-n-inline", "inline rows", query=q_profile("inline"), sub="inline"))
    ids.append(metric("x-n-passive", "passive rows", query=q_profile("passive"), sub="passive"))
    ids.append(metric("x-n-vfw", "vfw rows", query=q_profile("vfw"), sub="vfw"))
    ids.append(pie("x-docs-share", "Rows share by profile"))

    compare_fields = [
        ("x-cpu", "CPU%", "VNF_cpu_utilization_pct"),
        ("x-mem", "mem%", "VNF_memory_utilization_pct"),
        ("x-mqtt-p99", "MQTT p99 ms", "MQTT_package_latency_p99_ms"),
        ("x-mqtt-loss", "MQTT loss%", "MQTT_package_loss_pct"),
        ("x-offered-mbps", "offered_mbps", "offered_load_mbps"),
        ("x-offered-pps", "offered_pps", "offered_load_pps"),
    ]
    for vid, label, field in compare_fields:
        ids.append(hbar(vid, f"Cross: avg {label} by profile", field))

    trend_specs = [
        ("x-cpu-vcpu", "CPU% vs vCPU", "VNF_cpu_utilization_pct", "vCPU_cores", 1),
        ("x-cpu-mem", "CPU% vs memory MB", "VNF_cpu_utilization_pct", "VNF_memory_MB", 64),
        ("x-memutil-mem", "mem% vs memory MB", "VNF_memory_utilization_pct", "VNF_memory_MB", 64),
        ("x-mqtt-p99-lc", "MQTT p99 vs LC", "MQTT_package_latency_p99_ms", "Link_Capacity_limit_Mbps", 25),
        ("x-mqtt-loss-lc", "MQTT loss% vs LC", "MQTT_package_loss_pct", "Link_Capacity_limit_Mbps", 25),
        ("x-offered-lc", "offered_mbps vs LC", "offered_load_mbps", "Link_Capacity_limit_Mbps", 25),
        ("x-offered-pps-lc", "offered_pps vs LC", "offered_load_pps", "Link_Capacity_limit_Mbps", 25),
        ("x-cpu-lc", "CPU% vs LC", "VNF_cpu_utilization_pct", "Link_Capacity_limit_Mbps", 25),
    ]
    for vid, label, y, x, iv in trend_specs:
        ids.append(line(vid, f"Cross: {label}", y, x, iv, split_field="vnf_profile"))


    panels: list[dict] = []
    panels += layout_grid(5, cols=5, start_index=1, start_y=0, h=8)
    panels += layout_grid(6, cols=3, start_index=6, start_y=8, h=14)
    panels += layout_grid(8, cols=2, start_index=12, start_y=8 + 2 * 14, h=14)

    put_dash(
        "capstone-cross-profile",
        "Capstone: Cross-profile Compare",
        "Compare inline / passive / vfw side by side (48-col landscape)",
        ids,
        panels,
    )


def provision_profile(profile: str, specialty: list[tuple[str, str]]) -> None:
    prefix = f"p-{profile}"
    q = q_profile(profile)
    ids = []

    ids.append(metric(f"{prefix}-n", f"{profile} rows", query=q, sub=profile))
    common_metrics = [
        ("cpu", "avg CPU%", "VNF_cpu_utilization_pct"),
        ("mem", "avg mem%", "VNF_memory_utilization_pct"),
        ("mqtt-p99", "avg MQTT p99", "MQTT_package_latency_p99_ms"),
        ("mqtt-loss", "avg MQTT loss%", "MQTT_package_loss_pct"),
        ("offered-mbps", "avg offered_mbps", "offered_load_mbps"),
    ]
    for key, label, field in common_metrics:
        ids.append(metric(f"{prefix}-{key}", f"{profile}: {label}", field, q, profile))

    for field, label in specialty:
        ids.append(metric(f"{prefix}-sp-{label}", f"{profile}: {label}", field, q, profile))

    within = [
        ("cpu-vcpu", "CPU% vs vCPU", "VNF_cpu_utilization_pct", "vCPU_cores", 1),
        ("cpu-mem", "CPU% vs memory", "VNF_cpu_utilization_pct", "VNF_memory_MB", 64),
        ("memutil-mem", "mem% vs memory", "VNF_memory_utilization_pct", "VNF_memory_MB", 64),
        ("mqtt-p99-lc", "MQTT p99 vs LC", "MQTT_package_latency_p99_ms", "Link_Capacity_limit_Mbps", 25),
        ("mqtt-loss-lc", "MQTT loss% vs LC", "MQTT_package_loss_pct", "Link_Capacity_limit_Mbps", 25),
        ("offered-lc", "offered_mbps vs LC", "offered_load_mbps", "Link_Capacity_limit_Mbps", 25),
        ("offered-pps-lc", "offered_pps vs LC", "offered_load_pps", "Link_Capacity_limit_Mbps", 25),
        ("cpu-lc", "CPU% vs LC", "VNF_cpu_utilization_pct", "Link_Capacity_limit_Mbps", 25),
    ]
    for key, label, y, x, iv in within:
        ids.append(line(f"{prefix}-{key}", f"{profile}: {label}", y, x, iv, query=q))

    for field, label in specialty:
        ids.append(
            line(
                f"{prefix}-sptrend-{label}-vcpu",
                f"{profile}: {label} vs vCPU",
                field,
                "vCPU_cores",
                1,
                query=q,
            )
        )
        ids.append(
            line(
                f"{prefix}-sptrend-{label}-lc",
                f"{profile}: {label} vs LC",
                field,
                "Link_Capacity_limit_Mbps",
                25,
                query=q,
            )
        )
        ids.append(
            hbar(
                f"{prefix}-spbar-{label}-vcpu",
                f"{profile}: {label} by vCPU",
                field,
                query=q,
                seg="vCPU_cores",
            )
        )

    n_metric = 1 + len(common_metrics) + len(specialty)
    n_rest = len(ids) - n_metric

    metric_cols = min(6, max(4, n_metric))
    panels = layout_grid(n_metric, cols=metric_cols, start_index=1, start_y=0, h=8)
    y0 = ((n_metric + metric_cols - 1) // metric_cols) * 8
    panels += layout_grid(n_rest, cols=2, start_index=n_metric + 1, start_y=y0, h=14)

    put_dash(
        f"capstone-{profile}",
        f"Capstone: {profile}",
        f"Within-{profile} comparisons (48-col landscape)",
        ids,
        panels,
    )


def main() -> None:
    wait_kibana()
    http(
        "POST",
        "/api/saved_objects/index-pattern/capstone-dataset?overwrite=true",
        {"attributes": {"title": "capstone-dataset", "timeFieldName": ""}},
    )
    print("[index-pattern] capstone-dataset")

    provision_cross()
    provision_profile(
        "inline",
        [
            ("inline_analyzed_packets_per_sec", "analyzed_pps"),
            ("inline_blocked_packets_per_sec", "blocked_pps"),
            ("MQTT_package_latency_average_ms", "mqtt_avg_ms"),
        ],
    )
    provision_profile(
        "passive",
        [
            ("passive_processed_packets_per_sec", "processed_pps"),
            ("passive_alerts_per_sec", "alerts_ps"),
            ("passive_daq_drops_per_sec", "daq_drops_ps"),
        ],
    )
    provision_profile(
        "vfw",
        [
            ("vfw_forwarded_packets_per_sec", "forwarded_pps"),
            ("vfw_dropped_packets_per_sec", "dropped_pps"),
        ],
    )


    try:
        http("DELETE", "/api/saved_objects/dashboard/capstone-overview")
        print("[del] legacy capstone-overview")
    except Exception as e:
        print(f"[del] capstone-overview skipped: {e}")

    print("[done] dashboards:")
    print(f"  {KBN}/app/dashboards#/view/capstone-cross-profile")
    print(f"  {KBN}/app/dashboards#/view/capstone-inline")
    print(f"  {KBN}/app/dashboards#/view/capstone-passive")
    print(f"  {KBN}/app/dashboards#/view/capstone-vfw")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        raise
