#!/usr/bin/env python3
"""Tiny server health checker.

cloud-init copies this file to /opt/health/health.py on the new server and a
cron job runs it every hour, appending the output to /var/log/health.log.

It checks three things:
  * disk usage of "/"           (shutil.disk_usage)
  * memory used                 (/proc/meminfo: MemTotal and MemAvailable)
  * whether some services run   (systemctl is-active <name>)
"""

import shutil
import subprocess
from datetime import datetime

# Edit this list to watch more services, e.g. ["cron", "ssh", "nginx"].
SERVICES = ["cron"]

# Above these percentages the report says WARNING.
DISK_WARN = 90
MEMORY_WARN = 90


def disk_percent(path="/"):
    """Percentage of the root disk that is used."""
    usage = shutil.disk_usage(path)
    return usage.used / usage.total * 100


def memory_percent():
    """Percentage of memory in use, read straight from the kernel."""
    values = {}
    with open("/proc/meminfo") as meminfo:
        for line in meminfo:
            # Each line looks like:  MemTotal:       16318432 kB
            key, rest = line.split(":", 1)
            values[key] = int(rest.split()[0])
    total = values["MemTotal"]
    available = values["MemAvailable"]
    return (total - available) / total * 100


def service_active(name):
    """True if systemd says the service is running."""
    result = subprocess.run(
        ["systemctl", "is-active", name], capture_output=True, text=True
    )
    return result.stdout.strip() == "active"


def build_report():
    """Collect all checks into a short text report."""
    disk = disk_percent()
    memory = memory_percent()
    lines = [
        f"Health check {datetime.now():%Y-%m-%d %H:%M}",
        f"  disk   /     : {disk:5.1f}% used" + ("  WARNING" if disk > DISK_WARN else ""),
        f"  memory       : {memory:5.1f}% used" + ("  WARNING" if memory > MEMORY_WARN else ""),
    ]
    for name in SERVICES:
        state = "active" if service_active(name) else "NOT ACTIVE  WARNING"
        lines.append(f"  service {name:<6}: {state}")
    return "\n".join(lines)


def main():
    print(build_report())
    print()


if __name__ == "__main__":
    main()
