from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class Device(BaseModel):
    name: str
    vendor: str
    vendor_os: str
    model: str
    role: str
    site: Literal["production", "dr"]
    ip: str


class Flow(BaseModel):
    name: str
    src: str
    dst: str
    dst_port: int
    proto: Literal["tcp", "udp"]
    flow_class: Literal["user", "app", "replication", "vpn", "backup"]
    baseline_bps: int


class Topology(BaseModel):
    devices: list[Device]
    flows: list[Flow]

    def device(self, name: str) -> Device:
        for d in self.devices:
            if d.name == name:
                return d
        raise KeyError(name)

    def devices_by_vendor_os(self, vendor_os: str) -> list[Device]:
        return [d for d in self.devices if d.vendor_os == vendor_os]


def load_topology(path: str | Path) -> Topology:
    raw = yaml.safe_load(Path(path).read_text())
    topo = Topology(devices=raw["devices"], flows=raw["flows"])
    names = {d.name for d in topo.devices}
    for f in topo.flows:
        if f.src not in names or f.dst not in names:
            raise ValueError(f"flow {f.name} references unknown device")
    return topo
