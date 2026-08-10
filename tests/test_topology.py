import ipaddress

from synthgen.common.topology import load_topology

TOPO = load_topology("topology/network.yaml")

def test_device_count_and_sites():
    assert len(TOPO.devices) == 27
    assert {d.site for d in TOPO.devices} == {"production", "dr"}

def test_ips_unique_and_in_site_subnet():
    ips = [d.ip for d in TOPO.devices]
    assert len(ips) == len(set(ips))
    for d in TOPO.devices:
        net = "10.10.0.0/16" if d.site == "production" else "10.20.0.0/16"
        assert ipaddress.ip_address(d.ip) in ipaddress.ip_network(net), d.name

def test_flow_endpoints_exist():
    names = {d.name for d in TOPO.devices}
    for f in TOPO.flows:
        assert f.src in names, f.name
        assert f.dst in names, f.name

def test_inter_site_flows_present():
    classes = set()
    for f in TOPO.flows:
        if TOPO.device(f.src).site != TOPO.device(f.dst).site:
            classes.add(f.flow_class)
    assert {"vpn", "replication", "backup"} <= classes

def test_lookup_helpers():
    assert TOPO.device("cisco-asa-dr").vendor_os == "asa"
    assert len(TOPO.devices_by_vendor_os("asa")) == 1
