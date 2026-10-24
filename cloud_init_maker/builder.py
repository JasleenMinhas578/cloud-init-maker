"""Build the cloud-init config.

The flow is always the same:

    ServerOptions (plain answers)  ->  dict  ->  YAML text  ->  file on disk

We build a normal Python dict first and let PyYAML turn it into text.
That way indentation is always right and we never glue strings together.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The health checker lives in the repo at templates/health.py.
# __file__ is .../cloud_init_maker/builder.py, so two parents up is the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
HEALTH_TEMPLATE = REPO_ROOT / "templates" / "health.py"

# Where things end up on the new server.
HEALTH_SCRIPT = "/opt/health/health.py"
HEALTH_LOG = "/var/log/health.log"
HEALTH_CRON = "/etc/cron.d/health"


@dataclass
class ServerOptions:
    """Everything the user told us. One field per question."""

    username: str
    passwordless_sudo: bool = True
    ssh_key: str | None = None
    hostname: str | None = None
    timezone: str | None = None
    packages: list[str] = field(default_factory=list)
    runcmd: list[str] = field(default_factory=list)
    health: bool = False


def build_config(opts: ServerOptions) -> dict:
    """Turn the answers into a cloud-init config dict."""
    # --- the user block -------------------------------------------------
    user: dict = {
        "name": opts.username,
        "shell": "/bin/bash",
        "groups": ["sudo"],
    }
    if opts.passwordless_sudo:
        user["sudo"] = "ALL=(ALL) NOPASSWD:ALL"
    if opts.ssh_key:
        # IMPORTANT: the key goes *inside* the user entry, not at the top level.
        user["ssh_authorized_keys"] = [opts.ssh_key]

    config: dict = {"users": [user]}

    # --- optional simple settings ----------------------------------------
    if opts.hostname:
        config["hostname"] = opts.hostname
        # Also put the hostname in /etc/hosts so "sudo" does not complain
        # about being unable to resolve the host name.
        config["manage_etc_hosts"] = True
    if opts.timezone:
        config["timezone"] = opts.timezone

    # --- packages, files and first-boot commands -------------------------
    packages = list(opts.packages)
    runcmd = list(opts.runcmd)

    if opts.health:
        packages += ["python3", "python3-venv"]
        config["write_files"] = health_files()
        # Run the checker once right away so /var/log/health.log is not empty.
        runcmd.append(f"python3 {HEALTH_SCRIPT} >> {HEALTH_LOG} 2>&1")

    if packages:
        config["package_update"] = True  # apt update before installing
        config["packages"] = _unique(packages)
    if runcmd:
        config["runcmd"] = runcmd

    return config


def health_files() -> list[dict]:
    """The write_files entries for the health checker: the script and a cron job."""
    script = HEALTH_TEMPLATE.read_text()
    # cron.d format: minute hour day month weekday  user  command
    cron_line = f"0 * * * * root /usr/bin/python3 {HEALTH_SCRIPT} >> {HEALTH_LOG} 2>&1\n"
    return [
        {"path": HEALTH_SCRIPT, "permissions": "0755", "content": script},
        {"path": HEALTH_CRON, "permissions": "0644", "content": cron_line},
    ]


# --- YAML output --------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    """A SafeDumper with two readability tweaks.

    1. List items are indented under their key (PyYAML's default puts the
       dash at the same level as the key, which is valid but hard to read).
    2. Multi-line strings use the | block style (see _str_representer).
    """

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _str_representer(dumper: yaml.SafeDumper, text: str):
    style = "|" if "\n" in text else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", text, style=style)


_Dumper.add_representer(str, _str_representer)


def to_yaml(config: dict) -> str:
    """Dump the dict as YAML text, with the required #cloud-config header."""
    body = yaml.dump(
        config,
        Dumper=_Dumper,
        sort_keys=False,          # keep our order (users first)
        default_flow_style=False,  # block style, one item per line
        width=1000,                # never wrap long lines such as SSH keys
        allow_unicode=True,
    )
    return "#cloud-config\n" + body


# --- validation ---------------------------------------------------------------


def validate_text(text: str) -> dict:
    """Re-load the YAML we just wrote. Raises ValueError if something is off."""
    first_line = text.splitlines()[0] if text else ""
    if first_line != "#cloud-config":
        raise ValueError("first line must be exactly '#cloud-config'")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("top level of the file must be a mapping")
    return data


def cloud_init_schema_check(path: Path) -> str | None:
    """Run `cloud-init schema` if the tool is installed. Returns its output, or None."""
    if shutil.which("cloud-init") is None:
        return None
    result = subprocess.run(
        ["cloud-init", "schema", "--config-file", str(path)],
        capture_output=True,
        text=True,
    )
    return (result.stdout + result.stderr).strip()


def lxd_launch_command(path: Path, name: str = "test1") -> str:
    """The exact command to start an LXD container using the generated file."""
    return f'sudo lxc launch ubuntu:24.04 {name} --config=user.user-data="$(cat {path})"'


def _unique(items: list[str]) -> list[str]:
    """Remove duplicates but keep the original order."""
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
