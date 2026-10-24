"""Interactive questions.

Small helpers that ask one thing each, plus `ask_everything` which walks the
user through all questions and returns a ServerOptions.
"""

from __future__ import annotations

from pathlib import Path

from .builder import ServerOptions

# Keys we look for, in order of preference.
SSH_KEY_CANDIDATES = [
    Path.home() / ".ssh" / "id_ed25519.pub",
    Path.home() / ".ssh" / "id_rsa.pub",
]


def find_ssh_key() -> tuple[Path, str] | None:
    """Return (path, key text) for the first public key we find, or None."""
    for path in SSH_KEY_CANDIDATES:
        if path.is_file():
            key = path.read_text().strip()
            if key:
                return path, key
    return None


def read_ssh_key_file(path: str | Path) -> str:
    """Read a public key file and return its single line of text."""
    return Path(path).expanduser().read_text().strip()


# --- one question each ------------------------------------------------------


def ask(prompt: str, default: str | None = None) -> str:
    """Ask a free-text question. Enter accepts the default (may be empty)."""
    hint = f" [{default}]" if default else ""
    answer = input(f"{prompt}{hint}: ").strip()
    return answer or (default or "")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def ask_lines(prompt: str) -> list[str]:
    """Collect lines until the user enters an empty line."""
    print(f"{prompt} (one per line, blank line to finish)")
    lines: list[str] = []
    while True:
        line = input("> ").strip()
        if not line:
            return lines
        lines.append(line)


def ask_ssh_key(preset: str | None) -> str | None:
    """Show the detected key and let the user confirm it, paste another, or skip."""
    if preset is None:
        found = find_ssh_key()
        if found:
            path, preset = found
            print(f"Found SSH public key at {path}:")
            print(f"  {preset}")
    else:
        print("SSH public key:")
        print(f"  {preset}")

    if preset and ask_yes_no("Use this key?", default=True):
        return preset

    pasted = ask("Paste a public key (or leave blank for none)")
    if not pasted:
        print("Warning: no SSH key. You will not be able to log in with SSH.")
        return None
    return pasted


# --- all questions ----------------------------------------------------------


def ask_everything(defaults: ServerOptions) -> ServerOptions:
    """Walk through every question. `defaults` come from the command-line flags."""
    username = ask("Username", defaults.username)
    sudo = ask_yes_no("Give sudo access without a password?", defaults.passwordless_sudo)
    ssh_key = ask_ssh_key(defaults.ssh_key)
    hostname = ask("Hostname (optional)", defaults.hostname) or None
    timezone = ask("Timezone, e.g. America/St_Johns (optional)", defaults.timezone) or None

    packages_text = ask("Extra packages, comma-separated (optional)", ", ".join(defaults.packages))
    packages = split_csv(packages_text)

    runcmd = defaults.runcmd or ask_lines("Commands to run on first boot (optional)")
    health = ask_yes_no("Include the server health checker?", defaults.health)

    return ServerOptions(
        username=username,
        passwordless_sudo=sudo,
        ssh_key=ssh_key,
        hostname=hostname,
        timezone=timezone,
        packages=packages,
        runcmd=runcmd,
        health=health,
    )


def split_csv(text: str) -> list[str]:
    """'nginx, git,  htop' -> ['nginx', 'git', 'htop']"""
    return [item.strip() for item in text.split(",") if item.strip()]
