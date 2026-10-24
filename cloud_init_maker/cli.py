"""Command-line entry point: `cloud-init-maker`.

Two ways to use it:
  * interactive  -> just run `cloud-init-maker` and answer the questions
  * scripted     -> pass flags for every answer and add --yes to skip questions
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from . import __version__
from .builder import (
    ServerOptions,
    build_config,
    cloud_init_schema_check,
    lxd_launch_command,
    to_yaml,
    validate_text,
)
from .questions import ask_everything, find_ssh_key, read_ssh_key_file, split_csv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cloud-init-maker",
        description="Answer a few questions and get a valid cloud-init user-data.yaml.",
    )
    parser.add_argument("--user", help="username to create (default: your current user)")
    parser.add_argument(
        "--sudo",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="sudo without a password (--sudo / --no-sudo, default: yes)",
    )
    parser.add_argument("--ssh-key-file", help="path to a public key, e.g. ~/.ssh/id_ed25519.pub")
    parser.add_argument("--ssh-key", help="the public key itself as text")
    parser.add_argument("--hostname", help="hostname for the server")
    parser.add_argument("--timezone", help="timezone, e.g. America/St_Johns")
    parser.add_argument("--packages", help="comma-separated packages to install, e.g. nginx,git")
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        metavar="COMMAND",
        help="command to run on first boot (repeat the flag for more)",
    )
    parser.add_argument(
        "--health",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include the hourly server health checker",
    )
    parser.add_argument("--output", default="user-data.yaml", help="where to write (default: user-data.yaml)")
    parser.add_argument("--yes", "-y", action="store_true", help="no questions, accept flags and defaults")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def options_from_args(args: argparse.Namespace) -> ServerOptions:
    """Build the starting ServerOptions from flags, filling gaps with defaults."""
    if args.ssh_key:
        ssh_key: str | None = args.ssh_key.strip()
    elif args.ssh_key_file:
        ssh_key = read_ssh_key_file(args.ssh_key_file)
    elif args.yes:
        # No questions will be asked, so look for a key in ~/.ssh ourselves.
        # (In interactive mode the SSH question does this and shows the path.)
        found = find_ssh_key()
        ssh_key = found[1] if found else None
    else:
        ssh_key = None

    return ServerOptions(
        username=args.user or getpass.getuser(),
        passwordless_sudo=True if args.sudo is None else args.sudo,
        ssh_key=ssh_key,
        hostname=args.hostname,
        timezone=args.timezone,
        packages=split_csv(args.packages or ""),
        runcmd=list(args.run),
        health=bool(args.health),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    opts = options_from_args(args)

    if not args.yes:
        print("cloud-init-maker: press Enter to accept the value in [brackets].\n")
        opts = ask_everything(opts)

    if not opts.ssh_key:
        print("Warning: no SSH public key found or given. SSH login will not work.", file=sys.stderr)

    # dict -> YAML -> check -> file
    config = build_config(opts)
    text = to_yaml(config)
    validate_text(text)  # raises if our own output does not load back

    output = Path(args.output)
    output.write_text(text)
    print(f"\nWrote {output} ({len(text.splitlines())} lines). YAML re-loaded OK.")

    schema_result = cloud_init_schema_check(output)
    if schema_result is None:
        print("cloud-init is not installed here, skipped `cloud-init schema` check.")
    else:
        print("cloud-init schema check:")
        print(schema_result)

    print("\nLaunch an LXD container with it:")
    print(f"  {lxd_launch_command(output)}")
    print("(drop `sudo` if your user is in the lxd group)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
