from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from datetime import UTC, datetime

from synthgen import GLOBAL_SEED
from synthgen.common.topology import load_topology
from synthgen.netflow_gen import encoder as nf_encoder
from synthgen.netflow_gen.source import generate_records as nf_generate_records
from synthgen.syslog_gen import asa_source, ios_source, meraki_source, panw_source
from synthgen.syslog_gen.emitter import UdpSender

_SOURCES = {
    "syslog-asa": asa_source.generate_batch,
    "syslog-ios": ios_source.generate_batch,
    "syslog-panw": panw_source.generate_batch,
    "syslog-meraki": meraki_source.generate_batch,
}

# NetFlow v9 tuning
_NF_MTU = 1400
_NF_TEMPLATE_EVERY_N = 20   # re-send template flowset every N packets
_NF_MAX_PKTS_PER_SEC = 64   # upper bound for deterministic sequence derivation


def _nf_chunks(records: list, global_pkt_idx: int, first_of_tick: bool = False):
    """Yield (chunk, include_template) slices that fit within _NF_MTU bytes.

    Template inclusion rules:
      1. Always in the first packet of every tick (pkt_offset == 0) — guarantees
         the agent has a template before the accompanying data records every second.
      2. Every _NF_TEMPLATE_EVERY_N-th packet globally — keeps the template
         refreshing for any new listener that joins mid-stream.
    """
    max_with = (
        _NF_MTU
        - nf_encoder.HEADER_SIZE
        - nf_encoder.TEMPLATE_FS_SIZE
        - nf_encoder.DATA_FS_HEADER_SIZE
    ) // nf_encoder.RECORD_SIZE

    max_without = (
        _NF_MTU
        - nf_encoder.HEADER_SIZE
        - nf_encoder.DATA_FS_HEADER_SIZE
    ) // nf_encoder.RECORD_SIZE

    pkt_offset = 0
    i = 0
    while i < len(records):
        include_tmpl = (pkt_offset == 0 and first_of_tick) or (
            global_pkt_idx % _NF_TEMPLATE_EVERY_N == 0
        )
        limit = max_with if include_tmpl else max_without
        yield records[i : i + limit], include_tmpl
        i += limit
        global_pkt_idx += 1
        pkt_offset += 1


def _run_netflow(args) -> None:
    topo = load_topology(args.topology)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.target_host, args.target_port)
    print(f"synthgen netflow -> {args.target_host}:{args.target_port}", flush=True)

    pkt_total = 0
    while True:
        now = datetime.now(UTC)
        epoch_sec = int(now.timestamp())
        sys_uptime_ms = int(now.timestamp() * 1000) & 0xFFFFFFFF
        unix_secs = epoch_sec

        records = nf_generate_records(topo, now, args.seed)

        # Derive packet sequence deterministically from wall-clock time.
        # epoch_sec * _NF_MAX_PKTS_PER_SEC gives a monotone counter per second
        # without relying on module-level mutable state.
        global_pkt_base = (epoch_sec * _NF_MAX_PKTS_PER_SEC) % (2**32)

        for pkt_offset, (chunk, include_tmpl) in enumerate(
            _nf_chunks(records, global_pkt_base, first_of_tick=True)
        ):
            sequence = (global_pkt_base + pkt_offset) & 0xFFFFFFFF
            pkt = nf_encoder.build_packet(
                chunk, sys_uptime_ms, unix_secs, sequence, include_tmpl
            )
            try:
                sock.sendto(pkt, target)
            except OSError as exc:
                print(
                    f"netflow send failed ({exc}); skipping packet",
                    file=sys.stderr,
                    flush=True,
                )
            pkt_total += 1

        if pkt_total and pkt_total % 60 < 2:
            print(f"netflow: pkt_total={pkt_total}", flush=True)

        time.sleep(max(0.0, 1.0 - (datetime.now(UTC) - now).total_seconds()))


def main() -> None:
    parser = argparse.ArgumentParser(prog="synthgen")
    sub = parser.add_subparsers(dest="mode", required=True)

    for mode in ("syslog-asa", "syslog-ios", "syslog-panw", "syslog-meraki"):
        p = sub.add_parser(mode)
        p.add_argument("--target-host", required=True)
        p.add_argument("--target-port", type=int, required=True)
        p.add_argument("--topology", default="topology/network.yaml")
        p.add_argument("--seed", type=int, default=GLOBAL_SEED)

    nf = sub.add_parser("netflow")
    nf.add_argument("--target-host", required=True)
    nf.add_argument("--target-port", type=int, required=True)
    nf.add_argument("--topology", default="topology/network.yaml")
    nf.add_argument("--seed", type=int, default=GLOBAL_SEED)

    db = sub.add_parser("db-workload")
    db.add_argument("--seed", type=int, default=GLOBAL_SEED)

    mw = sub.add_parser("meraki-webhook")
    mw.add_argument("--target-host", required=True)
    mw.add_argument("--target-port", type=int, required=True)
    mw.add_argument("--seed", type=int, default=GLOBAL_SEED)

    args = parser.parse_args()

    if args.mode == "netflow":
        _run_netflow(args)
        return

    if args.mode == "db-workload":
        from synthgen.db_workload import run as db_run
        db_run(seed=args.seed)
        return

    if args.mode == "meraki-webhook":
        from synthgen.meraki_webhook import run as mw_run
        secret = os.environ.get("MERAKI_WEBHOOK_SECRET", "synthetic-meraki-secret")
        url = f"http://{args.target_host}:{args.target_port}/meraki/events"
        mw_run(url, secret=secret, seed=args.seed)
        return

    topo = load_topology(args.topology)
    sender = UdpSender(args.target_host, args.target_port)
    generate_batch = _SOURCES[args.mode]
    print(f"synthgen {args.mode}: -> {args.target_host}:{args.target_port}", flush=True)
    sent = 0
    while True:
        tick = datetime.now(UTC)
        for line in generate_batch(topo, tick, args.seed):
            try:
                sender.send(line)
                sent += 1
            except OSError as exc:
                print(f"send failed ({exc}); retrying next tick", file=sys.stderr, flush=True)
                break
        if sent and sent % 500 < 10:
            print(f"sent={sent}", flush=True)
        time.sleep(max(0.0, 1.0 - (datetime.now(UTC) - tick).total_seconds()))


if __name__ == "__main__":
    main()
