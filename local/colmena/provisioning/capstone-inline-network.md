# Capstone inline data-plane provisioning

The Capstone management network remains on `vmbr0`. The inline data plane uses two host-local, addressless bridges on `pve01`.

## Topology

| Guest | PVE NIC | Bridge | Guest NIC | MAC | Address |
|---|---|---|---|---|---|
| IoT CT100 | net1 | vmbr110 | eth1 | `02:77:10:00:01:00` | `10.77.10.2/30` |
| VNF VM101 ingress | net1 | vmbr110 | ens19 | `02:77:10:00:01:01` | `10.77.10.1/30` |
| VNF VM101 egress | net2 | vmbr120 | ens20 | `02:77:20:00:01:01` | `10.77.20.1/30` |
| Broker CT103 | net1 | vmbr120 | eth1 | `02:77:20:00:01:03` | `10.77.20.2/30` |

No data-plane interface has a default gateway. Management continues through `net0` and `192.168.88.0/24`.

## Applied PVE bridge configuration

Stored on `pve01` as `/etc/network/interfaces.d/capstone-vmbr`:

```text
auto vmbr110
iface vmbr110 inet manual
    bridge-ports none
    bridge-stp off
    bridge-fd 0

auto vmbr120
iface vmbr120 inet manual
    bridge-ports none
    bridge-stp off
    bridge-fd 0
```

The pre-change backup is under:

```text
/root/capstone-phase2-backup/20260712-163704
```

The bridges were brought up individually with `ifup vmbr110` and `ifup vmbr120`; PVE networking and `vmbr0` were not reloaded.

## Applied guest NIC commands

```bash
pct set 100 --net1 name=eth1,bridge=vmbr110,firewall=1,hwaddr=02:77:10:00:01:00,ip=manual,type=veth
pct set 103 --net1 name=eth1,bridge=vmbr120,firewall=1,hwaddr=02:77:20:00:01:03,ip=manual,type=veth
qm set 101 --net1 virtio=02:77:10:00:01:01,bridge=vmbr110,firewall=1
qm set 101 --net2 virtio=02:77:20:00:01:01,bridge=vmbr120,firewall=1
```

CT100 and CT103 were rebooted after adding `net1`. VM101 accepted both virtio NICs through hotplug.

## Status checks

```bash
ip -br link show vmbr110
ip -br link show vmbr120
bridge link | grep 'master vmbr110'
bridge link | grep 'master vmbr120'
pct config 100 | grep '^net'
pct config 102 | grep '^net'
qm config 101 | grep '^net'
```

Expected bridge membership:

```text
vmbr110: CT100 net1, VM101 net1
vmbr120: CT103 net1, VM101 net2
```

## Rollback

First remove the guest data-plane configuration through Colmena. Then, from the PVE console:

```bash
qm set 101 --delete net2
qm set 101 --delete net1
pct set 103 --delete net1
pct set 100 --delete net1
ifdown vmbr120
ifdown vmbr110
rm /etc/network/interfaces.d/capstone-vmbr
```

Restart CT100/CT102 if PVE does not remove their interfaces live. Do not modify `net0`, `vmbr0`, or any default route during rollback.
