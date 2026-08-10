from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

from synthgen import GLOBAL_SEED
from synthgen.common.topology import load_topology
from synthgen.syslog_gen.asa_source import generate_batch
from synthgen.syslog_gen.emitter import UdpSender


def main() -> None:
    parser = argparse.ArgumentParser(prog="synthgen")
    sub = parser.add_subparsers(dest="mode", required=True)
    asa_p = sub.add_parser("syslog-asa")
    asa_p.add_argument("--target-host", required=True)
    asa_p.add_argument("--target-port", type=int, required=True)
    asa_p.add_argument("--topology", default="topology/network.yaml")
    asa_p.add_argument("--seed", type=int, default=GLOBAL_SEED)
    args = parser.parse_args()

    topo = load_topology(args.topology)
    sender = UdpSender(args.target_host, args.target_port)
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
