"""Web UI for cloud-init-maker, built with Streamlit.

Run it with:   streamlit run app.py

Same builder as the command-line tool, so both produce identical files.

Layout:
    header (what it is, where the file is used)
    left:  the form (server type, login, SSH key, server, software, monitoring)
    right: the file, updating live as you type, plus Download and how to use it
"""

import re
import tempfile
import zoneinfo
from pathlib import Path

import streamlit as st

from cloud_init_maker.builder import (
    ServerOptions,
    build_config,
    cloud_init_schema_check,
    lxd_launch_command,
    to_yaml,
    validate_text,
)
from cloud_init_maker.questions import find_ssh_key

st.set_page_config(page_title="cloud-init-maker", page_icon="☁️", layout="wide")

EXAMPLE_USER = "alice"  # shown in the preview until the user types their own name

# --- presets: pick a server type, get sensible software pre-filled -----------------

SERVER_TYPES = {
    "Plain Ubuntu (just a user and SSH)": {"packages": [], "runcmd": []},
    "Web server (nginx)": {
        "packages": ["nginx", "certbot"],
        "runcmd": ["systemctl enable --now nginx"],
    },
    "Python app server": {
        "packages": ["python3", "python3-venv", "python3-pip", "git", "nginx"],
        "runcmd": ["systemctl enable --now nginx"],
    },
    "Node.js app server": {
        "packages": ["nodejs", "npm", "git", "nginx"],
        "runcmd": ["systemctl enable --now nginx"],
    },
    "Database server (PostgreSQL)": {
        "packages": ["postgresql"],
        "runcmd": ["systemctl enable --now postgresql"],
    },
    "Docker host": {
        "packages": ["docker.io", "docker-compose-v2"],
        "runcmd": ["systemctl enable --now docker"],
    },
    "Dev box for learning Linux": {
        "packages": ["git", "htop", "curl", "vim", "tmux", "build-essential"],
        "runcmd": [],
    },
}

# Shown in the software dropdown. Users can also type any other package name.
SUGGESTED_SOFTWARE = sorted(
    {
        "nginx", "apache2", "certbot", "git", "htop", "curl", "wget", "vim", "tmux", "unzip",
        "docker.io", "docker-compose-v2", "postgresql", "mysql-server", "redis-server",
        "python3", "python3-venv", "python3-pip", "nodejs", "npm", "build-essential",
        "ufw", "fail2ban", "net-tools",
    }
)

TIMEZONES = ["UTC"] + sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith("Etc/"))

# --- styling -------------------------------------------------------------------------

st.markdown(
    """
<style>
  .block-container { padding-top: 1.2rem; max-width: 1250px; }
  #MainMenu, footer { visibility: hidden; }

  .hero { padding: 1.8rem 2rem; border-radius: 18px; color: white; text-align: center;
          background: linear-gradient(120deg, #1e3a8a 0%, #2563eb 55%, #06b6d4 100%);
          box-shadow: 0 10px 30px rgba(37, 99, 235, .25); }
  .hero h1 { margin: 0; font-size: 2.3rem; color: white; letter-spacing: -.5px; }
  .hero p  { margin: .4rem 0 0 0; font-size: 1.1rem; opacity: .95; }
  .hero .flow { margin-top: .9rem; font-size: .95rem; opacity: .9; }
  .hero .flow b { background: rgba(255,255,255,.18); padding: .25rem .6rem; border-radius: 999px; margin: 0 .15rem; }

  .pills { text-align: center; margin: .6rem 0 1.2rem 0; color: #475569; font-size: .9rem; }
  .pills span { display: inline-block; background: white; border: 1px solid #e2e8f0; border-radius: 999px;
                padding: .3rem .8rem; margin: .2rem; }

  .section { font-size: 1.05rem; font-weight: 700; margin: 1.1rem 0 .2rem 0; padding-top: .8rem; border-top: 1px solid #e2e8f0; }
  .section:first-child { border-top: none; padding-top: 0; margin-top: 0; }
  .hint { color: #64748b; font-size: .85rem; margin: -.6rem 0 .6rem 0; }

  div[data-testid="stVerticalBlockBorderWrapper"] { background: white; border-radius: 16px; }
  .card { background: white; border: 1px solid #e2e8f0; border-radius: 14px; padding: .8rem 1.2rem; }
  .card li { margin-bottom: .15rem; }
</style>
""",
    unsafe_allow_html=True,
)


def section(title: str) -> None:
    st.markdown(f'<div class="section">{title}</div>', unsafe_allow_html=True)


def hint(text: str) -> None:
    """One short line under a field saying what to put in it."""
    st.markdown(f'<div class="hint">{text}</div>', unsafe_allow_html=True)


# --- header -----------------------------------------------------------------------------

st.markdown(
    """
<div class="hero">
  <h1>☁️ cloud-init-maker</h1>
  <p>Fill in the form. Download one file. Your new Ubuntu server sets itself up on first boot.</p>
  <div class="flow"><b>1 · Fill the form</b> → <b>2 · Download user-data.yaml</b> → <b>3 · Launch a server with it</b> → <b>4 · Log in, it's ready</b></div>
</div>
<div class="pills">The file works anywhere Ubuntu runs:
  <span>🖥️ LXD (local)</span><span>☁️ AWS EC2</span><span>☁️ Azure VM</span><span>☁️ DigitalOcean</span><span>💻 Multipass</span>
</div>
""",
    unsafe_allow_html=True,
)

left, right = st.columns([1, 1], gap="large")

# --- the form (left) ----------------------------------------------------------------------

with left:
    with st.container(border=True):
        section("1 · What kind of server?")
        server_type = st.selectbox("Server type", list(SERVER_TYPES), label_visibility="collapsed")
        hint("Pick the closest match. It fills in the software below; you can change anything.")
        preset = SERVER_TYPES[server_type]

        section("2 · Your login")
        username = st.text_input("Username", placeholder=EXAMPLE_USER, key="username").strip()
        hint("The name you will type to log in. Lowercase letters and digits, no spaces.")
        if username and not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
            st.warning("Usernames use lowercase letters, digits, `-` and `_`, and cannot start with a digit.")
        sudo = st.toggle("Allow admin commands (sudo) without a password", value=True)
        hint("Keep this on. The user has no password, only a key, so sudo cannot ask for one.")

        section("3 · Your SSH public key")
        found = find_ssh_key()  # looks in ~/.ssh on the machine running this page
        use_found = False
        if found:
            use_found = st.checkbox(f"Use the key found on this computer ({found[0].name})", value=False)
        ssh_key = st.text_area(
            "Public key",
            key="ssh_key",
            height=80,
            placeholder="ssh-ed25519 AAAA...  (one long line)",
            disabled=use_found,
        ).strip()
        hint("This is how you log in. Paste the text of your <code>.pub</code> file. "
             "To see it, run <code>cat ~/.ssh/id_ed25519.pub</code>. No key yet? Run <code>ssh-keygen -t ed25519</code>.")
        if use_found:
            ssh_key = found[1]
        if ssh_key and not ssh_key.startswith(("ssh-", "ecdsa-")):
            st.warning("That does not look like a public key. It should start with `ssh-ed25519` or `ssh-rsa`.")

        section("4 · Server details (optional)")
        c1, c2 = st.columns(2)
        hostname = c1.text_input("Hostname", placeholder="web1").strip()
        timezone = c2.selectbox("Timezone", TIMEZONES, index=0)
        hint("Hostname: a short name for the server. Timezone: type to search, e.g. America/St_Johns.")

        section("5 · Software to install")
        packages = st.multiselect(
            "Packages",
            options=sorted(set(SUGGESTED_SOFTWARE) | set(preset["packages"])),
            default=preset["packages"],
            accept_new_options=True,
            label_visibility="collapsed",
            placeholder="Choose from the list or type a package name and press Enter",
        )
        hint("Any Ubuntu package name works, exactly as you would type after <code>apt install</code>.")
        runcmd_text = st.text_area(
            "Commands to run once on first boot (optional)",
            value="\n".join(preset["runcmd"]),
            height=80,
            placeholder="systemctl enable --now nginx",
        )
        hint("One command per line. They run as root after the software is installed.")

        section("6 · Monitoring (optional)")
        health = st.toggle("Add an hourly health report", value=False, key="health")
        hint("Writes disk, memory and service status to <code>/var/log/health.log</code> every hour.")

# --- the file (right) ------------------------------------------------------------------------

opts = ServerOptions(
    username=username or EXAMPLE_USER,
    passwordless_sudo=sudo,
    ssh_key=ssh_key or None,
    hostname=hostname or None,
    timezone=None if timezone == "UTC" else timezone,
    packages=[p.strip() for p in packages if p.strip()],
    runcmd=[line.strip() for line in runcmd_text.splitlines() if line.strip()],
    health=health,
)
text = to_yaml(build_config(opts))

with right:
    st.subheader("Your file: user-data.yaml")
    if not username:
        st.caption(f"Updates as you type. Showing the example name **{EXAMPLE_USER}** until you enter yours.")
    else:
        st.caption("Updates as you type.")

    lines = [f"creates user <b>{opts.username}</b>" + (" with password-free sudo" if sudo else "")]
    lines.append("lets you log in with your SSH key" if ssh_key else "⚠️ <b>no SSH key yet</b>, you could not log in")
    if opts.hostname:
        lines.append(f"names the server <b>{opts.hostname}</b>")
    if opts.timezone:
        lines.append(f"sets the clock to <b>{opts.timezone}</b>")
    if opts.packages:
        lines.append("installs " + ", ".join(f"<code>{p}</code>" for p in opts.packages))
    if opts.runcmd:
        lines.append(f"runs {len(opts.runcmd)} command{'s' if len(opts.runcmd) != 1 else ''} on first boot")
    if health:
        lines.append("logs a health report every hour")
    st.markdown('<div class="card"><b>This file:</b><ul>' + "".join(f"<li>{l}</li>" for l in lines) + "</ul></div>", unsafe_allow_html=True)
    st.write("")

    st.download_button(
        "⬇️  Download user-data.yaml",
        data=text,
        file_name="user-data.yaml",
        mime="text/yaml",
        type="primary",
        use_container_width=True,
        disabled=not (username and ssh_key),
        help="Fill in a username and an SSH key first." if not (username and ssh_key) else None,
    )

    try:
        validate_text(text)
    except ValueError as error:  # should never happen, but never hide it
        st.error(f"YAML problem: {error}")
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        tmp.write(text)
    schema = cloud_init_schema_check(Path(tmp.name))
    if schema is not None:
        st.code(schema, language=None)

    st.code(text, language="yaml")

    launch_steps = [
        lxd_launch_command(Path("user-data.yaml")),
        "sudo lxc exec test1 -- cloud-init status --wait",
        "sudo lxc list                      # find the IP",
        f"ssh {opts.username}@<ip>",
    ]
    if health:
        launch_steps.append("sudo lxc exec test1 -- cat /var/log/health.log")
    launch_steps.append("sudo lxc delete --force test1      # clean up")

    with st.expander("How to use this file"):
        st.markdown(
            f"""
**Locally with LXD** (install once: `sudo snap install lxd && sudo lxd init --minimal`)
```bash
{chr(10).join(launch_steps)}
```
**AWS EC2:** paste the file into *User data* when launching the instance.
**Azure VM:** paste it into *Custom data*.
**DigitalOcean:** paste it into *User data* on the Droplet form.

cloud-init runs on the **first boot only**. Changed the file? Launch a fresh server.
            """
        )

st.divider()
st.caption(
    "Open source, MIT licence. Code, tests and a command-line version: "
    "[github.com/JasleenMinhas578/cloud-init-maker](https://github.com/JasleenMinhas578/cloud-init-maker)"
)
