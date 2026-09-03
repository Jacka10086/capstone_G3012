#!/usr/bin/env python3
import json
import os

DS = {"type": "prometheus", "uid": "prometheus"}
PLUGIN = "12.0.7"

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wangzheng.json")



DEFAULT_CUSTOM = {
    "axisBorderShow": False,
    "axisCenteredZero": False,
    "axisColorMode": "text",
    "axisLabel": "",
    "axisPlacement": "auto",
    "barAlignment": 0,
    "barWidthFactor": 0.6,
    "drawStyle": "line",
    "fillOpacity": 0,
    "gradientMode": "none",
    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
    "insertNulls": False,
    "lineInterpolation": "linear",
    "lineWidth": 1,
    "pointSize": 5,
    "scaleDistribution": {"type": "linear"},
    "showPoints": "auto",
    "spanNulls": False,
    "stacking": {"group": "A", "mode": "none"},
    "thresholdsStyle": {"mode": "off"},
}

DEFAULT_THRESHOLDS = {
    "mode": "absolute",
    "steps": [{"color": "green"}, {"color": "red", "value": 80}],
}


def ts(pid, title, expr, x, y, w=12, h=8, description=None, editor_mode="code",
       extra_target=None, unit=None, legend=None, zero_fallback=False):
    wrapped = f"max({expr} or vector(0))" if zero_fallback else expr
    target = {
        "editorMode": "code" if zero_fallback else editor_mode,
        "expr": wrapped,
        "legendFormat": legend if legend else "__auto",
        "range": True,
        "refId": "A",
    }
    if extra_target:
        target.update(extra_target)
    defaults = {
        "color": {"mode": "palette-classic"},
        "custom": DEFAULT_CUSTOM,
        "mappings": [],
        "thresholds": DEFAULT_THRESHOLDS,
    }
    if unit:
        defaults["unit"] = unit
    panel = {
        "datasource": DS,
        "fieldConfig": {
            "defaults": defaults,
            "overrides": [],
        },
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": pid,
        "options": {
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"hideZeros": False, "mode": "single", "sort": "none"},
        },
        "pluginVersion": PLUGIN,
        "targets": [target],
        "title": title,
        "type": "timeseries",
    }
    if description:
        panel["description"] = description
    return panel


def ts2(pid, title, targets, x, y, w=12, h=6, description=None, unit=None):
    panel = ts(pid, title, targets[0][0], x, y, w=w, h=h, description=description,
               editor_mode="code", unit=unit, legend=targets[0][1])
    panel["targets"] = [
        {"editorMode": "code", "expr": e, "legendFormat": l, "range": True, "refId": chr(65 + i)}
        for i, (e, l) in enumerate(targets)
    ]
    return panel


def row(pid, title, y):
    return {
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "id": pid,
        "panels": [],
        "title": title,
        "type": "row",
    }


def status_heatmap(pid, title, checks, w=6, h=7, x=0, y=0):
    expr = " or\n".join(
        f'label_replace(max({q} or vector(0)), "check", "{label}", "__name__", ".*")'
        for label, q in checks
    )
    return {
        "id": pid,
        "type": "heatmap",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": DS,
        "targets": [{"expr": expr, "legendFormat": "{{check}}", "refId": "A"}],
        "fieldConfig": {
            "defaults": {
                "custom": {
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "scaleDistribution": {"type": "linear"},
                }
            },
            "overrides": [],
        },
        "options": {
            "calculate": False,
            "cellGap": 1,
            "color": {
                "exponent": 0.1,
                "fill": "green",
                "mode": "scheme",
                "reverse": False,
                "scale": "exponential",
                "scheme": "RdYlGn",
                "steps": 2,
            },
            "exemplars": {"color": "rgba(255,0,255,0.7)"},
            "filterValues": {"le": 1.0e-9},
            "legend": {"show": False},
            "rowsFrame": {"layout": "auto"},
            "tooltip": {"mode": "single", "showColorScale": False, "yHistogram": False},
            "yAxis": {"axisPlacement": "left", "reverse": False},
        },
        "pluginVersion": PLUGIN,
    }


def build():
    panels = []


    panels.append(row(100, "Status", 0))
    panels.append(status_heatmap(20, "Service of IoT", x=0, y=1, w=6, h=7,
                                 checks=[("node_exporter", 'capstone_service_up{machine="iot",service="node_exporter"}'),("mqtt-traffic", 'capstone_service_up{machine="iot",service="mqtt-traffic"}'),
                                         ("mqtt-probe", 'capstone_service_up{machine="iot",service="mqtt-probe"}'),
                                         ("zombie-traffic", 'capstone_service_up{machine="iot",service="zombie-traffic"}'),
                                         ("iperf3-client", 'capstone_service_up{machine="iot",service="iperf3-client"}')]))
    panels.append(status_heatmap(21, "Service of VNF", x=6, y=1, w=6, h=7,
                                 checks=[("node_exporter", 'capstone_service_up{machine="vnf",service="node_exporter"}'),("snort-inline", 'capstone_service_up{machine="vnf",service="snort-inline"}'),
                                         ("snort-passive", 'capstone_service_up{machine="vnf",service="snort-passive"}'),
                                         ("capstone-vfw", 'capstone_service_up{machine="vnf",service="capstone-vfw"}')]))
    panels.append(status_heatmap(22, "Service of Broker", x=12, y=1, w=6, h=7,
                                 checks=[("node_exporter", 'capstone_service_up{machine="broker",service="node_exporter"}'),("mosquitto", 'capstone_service_up{machine="broker",service="mosquitto"}'),
                                         ("iperf3-load-sink", 'capstone_service_up{machine="broker",service="iperf3-load-sink"}')]))
    panels.append(status_heatmap(23, "Service of Brain", x=18, y=1, w=6, h=7,
                                checks=[("node_exporter", 'capstone_service_up{machine="brain",service="node_exporter"}'),("prometheus", 'capstone_service_up{machine="brain",service="prometheus"}'),
                                        ("grafana", 'capstone_service_up{machine="brain",service="grafana"}'),
                                        ("elasticsearch", 'capstone_service_up{machine="brain",service="elasticsearch"}'),
                                        ("kibana", 'capstone_service_up{machine="brain",service="kibana"}')]))


    panels.append(row(104, "Traffic Flow (iot→vnf→broker)", 8))
    panels.append(ts2(26, "iot (out)",
                      [('rate(node_network_transmit_bytes_total{job="iot-devices",device="eth1"}[$__rate_interval]) * 8', "iot eth1 tx (10.77.10.2)")],
                      0, 9, h=6, description="iot egress traffic: eth1 tx (10.77.10.2)", unit="bps"))
    panels.append(ts2(27, "vnf (in+out)",
                      [('rate(node_network_receive_bytes_total{job="vnf-snort",device="ens19"}[$__rate_interval]) * 8', "vnf ens19 rx (10.77.10.1)"),
                       ('rate(node_network_transmit_bytes_total{job="vnf-snort",device="ens20"}[$__rate_interval]) * 8', "vnf ens20 tx (10.77.20.1)")],
                      12, 9, h=6, description="vnf forwarding: ens19 rx (10.77.10.1) vs ens20 tx (10.77.20.1)", unit="bps"))
    panels.append(ts2(28, "broker (in)",
                      [('rate(node_network_receive_bytes_total{job="broker-sink",device="eth1"}[$__rate_interval]) * 8', "broker eth1 rx (10.77.20.2)")],
                      0, 15, h=6, description="broker ingress traffic: eth1 rx (10.77.20.2)", unit="bps"))
    panels.append(ts(29, "snort-inline processing",
                     'label_replace(rate(capstone_snort_processed_packets_total{vnf="snort-inline"}[$__rate_interval]), "action", "processed", "", "") or\nlabel_replace(rate(capstone_snort_dropped_packets_total{vnf="snort-inline"}[$__rate_interval]), "action", "blocked", "", "")',
                     12, 15, h=6, description="snort-inline (IPS) processed vs blocked packet rate (pps)", editor_mode="code",
                     unit="pps", legend="{{action}}"))
    panels.append(ts(32, "snort-passive processing",
                     'label_replace(rate(capstone_snort_passive_processed_packets_total{vnf="snort-passive"}[$__rate_interval]), "action", "processed", "", "") or\nlabel_replace(rate(capstone_snort_passive_alerts_total{vnf="snort-passive"}[$__rate_interval]), "action", "alerts", "", "")',
                     0, 21, h=6, description="snort-passive (IDS) processed vs alerts packet rate (pps)", editor_mode="code",
                     unit="pps", legend="{{action}}"))
    panels.append(ts(33, "vfw processing",
                     'label_replace(rate(capstone_vfw_forwarded_packets_total{vnf="vfw"}[$__rate_interval]), "action", "forwarded", "", "") or\nlabel_replace(rate(capstone_vfw_dropped_packets_total{vnf="vfw"}[$__rate_interval]), "action", "dropped", "", "")',
                     12, 21, h=6, description="capstone-vfw (nftables) forwarded vs dropped packet rate (pps)", editor_mode="code",
                     unit="pps", legend="{{action}}"))


    panels.append(row(101, "iot", 27))
    panels.append(ts(2, "capstone-mqtt-traffic",
                     'rate(capstone_mqtt_messages_total{host="iot"}[$__rate_interval])',
                     0, 28, h=6, editor_mode="builder", unit="ops", legend="messages/s",
                     extra_target={"disableTextWrap": False, "fullMetaSearch": False,
                                   "includeNullMetadata": False, "useBackend": False},
                     zero_fallback=True))
    panels.append(ts(1, "capstone-mqtt-probe",
                     'capstone_mqtt_probe_latency_seconds_average{job="iot-devices"}',
                     12, 28, h=6, editor_mode="builder", unit="s", legend="latency",
                     extra_target={"disableTextWrap": False, "fullMetaSearch": False,
                                   "includeNullMetadata": True, "useBackend": False},
                     zero_fallback=True))
    panels.append(ts(3, "capstone-zombie-traffic",
                     'rate(capstone_zombie_packets_total{job="iot-devices"}[$__rate_interval])',
                     0, 34, h=6, editor_mode="builder", unit="pps", legend="packets/s",
                     extra_target={"disableTextWrap": False, "fullMetaSearch": False,
                                   "includeNullMetadata": True, "useBackend": False},
                     zero_fallback=True))
    panels.append(ts(4, "iperf3-client",
                     'capstone_iperf_throughput_bits_per_second{job="iot-devices"}',
                     12, 34, h=6, editor_mode="builder", unit="bps", legend="throughput",
                     extra_target={"disableTextWrap": False, "fullMetaSearch": False,
                                   "includeNullMetadata": True, "useBackend": False},
                     zero_fallback=True))
    panels.append(ts(17, "MQTT Latency p99",
                     'capstone_mqtt_probe_latency_seconds_p99{job="iot-devices"} * 1000',
                     0, 40, h=6, description="dataset MQTT_package_latency_p99_ms", editor_mode="code",
                     unit="ms", legend="p99", zero_fallback=True))
    panels.append(ts(24, "MQTT Loss",
                     'capstone_mqtt_probe_loss_ratio{job="iot-devices"} * 100',
                     12, 40, h=6, description="dataset MQTT_package_loss_pct", editor_mode="code",
                     unit="percent", legend="loss", zero_fallback=True))


    panels.append(row(102, "VNF", 46))
    panels.append(ts(9, "VNF Offered Load",
                     'sum(rate(node_network_receive_packets_total{job="vnf-snort",device="ens19"}[$__rate_interval]))',
                     0, 47, h=6, description="dataset offered_load_pps: IoT->VNF ingress load packet rate", editor_mode="code",
                     unit="pps", legend="ens19 rx"))
    panels.append(ts(10, "VNF CPU Utilization",
                     '100 - avg(rate(node_cpu_seconds_total{job="vnf-snort",mode="idle"}[$__rate_interval])) * 100',
                     12, 47, h=6, description="dataset VNF_cpu_utilization_pct", editor_mode="code",
                     unit="percent", legend="cpu"))
    panels.append(ts(11, "VNF Memory Utilization",
                     '100 * (1 - node_memory_MemAvailable_bytes{job="vnf-snort"} / node_memory_MemTotal_bytes{job="vnf-snort"})',
                     0, 53, h=6, description="dataset VNF_memory_utilization_pct", editor_mode="code",
                     unit="percent", legend="mem"))
    panels.append(ts(14, "Link Capacity",
                     'capstone_link_capacity_mbps',
                     12, 53, h=6, description="dataset Link_Capacity_limit_Mbps: current tc-tbf link limit (unlimited=0)", editor_mode="code",
                     unit="Mbps", legend="limit"))
    panels.append(ts(30, "vCPU Cores",
                     'count(node_cpu_seconds_total{job="vnf-snort",mode="idle"})',
                     0, 59, h=6, description="dataset vCPU_cores: VNF allocated CPU cores", editor_mode="code",
                     unit="short", legend="cores"))
    panels.append(ts(31, "VNF Memory (MB)",
                     'node_memory_MemTotal_bytes{job="vnf-snort"} / 1024 / 1024',
                     12, 59, h=6, description="dataset VNF_memory_MB: VNF allocated memory size", editor_mode="code",
                     unit="decmbytes", legend="mem"))


    panels.append(row(103, "broker", 71))
    panels.append(ts(15, "mosquitto",
                     'label_replace(sum(rate(capstone_mqtt_device_messages_total{job="iot-devices"}[$__rate_interval])), "stream", "devices", "", "") or\nlabel_replace(rate(capstone_mqtt_probe_messages_offered_total{job="iot-devices"}[$__rate_interval]), "stream", "probe", "", "")',
                     0, 72, h=6, description="MQTT device PUBLISH total rate vs probe message rate (msg/s)", editor_mode="code",
                     unit="ops", legend="{{stream}}"))




    panels.append(ts(18, "iperf3-load-sink:5202",
                     'capstone_iperf_sink_throughput_bits_per_second{job="broker-sink"} * on() clamp_max(capstone_service_up{machine="broker",service="iperf3-load-sink"}, 1)',
                     12, 72, h=6, description="broker receive-side iperf throughput (bps): capstone_iperf_sink_throughput_bits_per_second", editor_mode="code",
                     unit="bps", legend="receive"))
    panels.append(ts(25, "MQTT Device Traffic (msg/s)",
                     'rate(capstone_mqtt_device_messages_total{job="iot-devices"}[$__rate_interval])',
                     0, 78, h=6, description="per-device publish rate of 50 MQTT devices (msg/s), one line per device", editor_mode="code",
                     unit="cps", legend="{{room}}/{{device}}"))

    dashboard = {
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard",
                }
            ]
        },
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "links": [],
        "panels": panels,
        "preload": False,
        "schemaVersion": 41,
        "tags": [],
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": "WangZheng",
        "uid": "wangzheng",
        "version": 1,
        "weekStart": None,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
    print(f"wrote {OUT} with {len(panels)} panels")


if __name__ == "__main__":
    build()
