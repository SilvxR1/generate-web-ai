"""R5.1 network audit (TEST HARNESS ONLY — never part of the worker image's
entrypoint): run the worker inside its container while logging every DNS
name it resolves.

Started as root inside the worker container (by r5_product_e2e.py
--dns-audit), it:
1. starts a forwarding DNS logger on 127.0.0.77:53 that records each query
   name/type to the log and forwards it to the original resolver;
2. points /etc/resolv.conf at it (the container's own copy);
3. drops to the unprivileged worker user (setpriv, no new privileges) and
   runs `python -m app.worker <args>` with the environment it was given.

What it observes: names resolved through the system resolver (bun, the
Python worker's HTTP client, Chromium). Connections to literal IP
addresses would not appear; the report says so.
"""

import os
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

LOG = Path(os.environ.pop("GWA_DNS_AUDIT_LOG", "/audit/dns.log"))
LISTEN = ("127.0.0.77", 53)


def _qname(packet: bytes) -> tuple[str, int]:
    labels, i = [], 12
    while i < len(packet) and packet[i]:
        length = packet[i]
        labels.append(packet[i + 1 : i + 1 + length].decode("ascii", "replace"))
        i += 1 + length
    qtype = struct.unpack("!H", packet[i + 1 : i + 3])[0] if i + 3 <= len(packet) else 0
    return ".".join(labels), qtype


def serve(upstream: str) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(LISTEN)
    lock = threading.Lock()

    def handle(packet: bytes, client: tuple[str, int]) -> None:
        name, qtype = _qname(packet)
        with lock, LOG.open("a", encoding="utf-8") as log:
            log.write(f"{name}\t{qtype}\n")
        forward = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        forward.settimeout(5)
        try:
            forward.sendto(packet, (upstream, 53))
            answer, _ = forward.recvfrom(65535)
            server.sendto(answer, client)
        except OSError:
            pass
        finally:
            forward.close()

    while True:
        packet, client = server.recvfrom(65535)
        threading.Thread(target=handle, args=(packet, client), daemon=True).start()


def main() -> None:
    resolv = Path("/etc/resolv.conf").read_text(encoding="utf-8")
    upstream = next((line.split()[1] for line in resolv.splitlines() if line.startswith("nameserver")), "8.8.8.8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    threading.Thread(target=serve, args=(upstream,), daemon=True).start()
    Path("/etc/resolv.conf").write_text(f"nameserver {LISTEN[0]}\noptions timeout:5 attempts:1\n", encoding="utf-8")
    worker = [
        "setpriv",
        "--reuid=10001",
        "--regid=10001",
        "--init-groups",
        "--no-new-privs",
        "--",
        "/srv/worker/.venv/bin/python",
        "-m",
        "app.worker",
        *sys.argv[1:],
    ]
    sys.exit(subprocess.call(worker, cwd="/srv/worker"))  # noqa: S603 — fixed argv


if __name__ == "__main__":
    main()
