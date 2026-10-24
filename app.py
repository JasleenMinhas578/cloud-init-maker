"""Web UI for cloud-init-maker, built with Streamlit.

Run it with:   streamlit run app.py

Same builder as the command-line tool, so both produce identical files.

Layout:
    header (what it is, where it is used, one example use case)
    server type dropdown  ->  pre-fills the form
    form (login, SSH key, server, software, health)  ->  "Generate" button
    result: summary, download, YAML, launch commands
"""

import getpass
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
from cloud_init_maker.questions import find_ssh_key, split_csv

st.set_page_config(page_title="cloud-init-maker", page_icon="☁️", layout="centered")

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
  .block-container { padding-top: 1.2rem; max-width: 900px; }
  #MainMenu, footer { visibility: hidden; }

  .hero { padding: 2rem 2.2rem; border-radius: 18px; color: white; text-align: center;
          background: linear-gradient(120deg, #1e3a8a 0%, #2563eb 55%, #06b6d4 100%);
          box-shadow: 0 10px 30px rgba(37, 99, 235, .25); margin-bottom: 1rem; }
  .hero h1 { margin: 0; font-size: 2.4rem; color: white; letter-spacing: -.5px; }
  .hero p  { margin: .5rem 0 0 0; font-size: 1.15rem; opacity: .95; }
  .hero .flow { margin-top: 1rem; font-size: .95rem; opacity: .9; }
  .hero .flow b { background: rgba(255,255,255,.18); padding: .25rem .6rem; border-radius: 999px; margin: 0 .15rem; }

  .pills { text-align: center; margin: .6rem 0 1rem 0; color: #475569; font-size: .9rem; }
  .pills span { display: inline-block; background: white; border: 1px solid #e2e8f0; border-radius: 999px;
                padding: .3rem .8rem; margin: .2rem; }

  .usecase { background: #fffbeb; border: 1px solid #fde68a; border-radius: 14px; padding: 1rem 1.2rem; margin-bottom: .5rem; }
  .usecase h4 { margin: 0 0 .3rem 0; }
  .usecase p { margin: 0; color: #4b5563; }

  .card { background: white; border: 1px solid #e2e8f0; border-radius: 14px; padding: 1rem 1.2rem; }
  .card li { margin-bottom: .2rem; }
  div[data-testid="stForm"] { background: white; border-radius: 16px; padding: 1.4rem 1.6rem; border: 1px solid #e2e8f0; }
</style>
""",
    unsafe_allow_html=True,
)

# --- header -----------------------------------------------------------------------------

st.markdown(
    """
<div class="hero">
  <h1>☁️ cloud-init-maker</h1>
  <p>Fill in one form. Get a file. Your new Ubuntu server sets itself up on first boot.</p>
  <div class="flow"><b>1 · Fill the form</b> → <b>2 · Download user-data.yaml</b> → <b>3 · Launch a server</b> → <b>4 · Log in, it's ready</b></div>
</div>
<div class="pills">The file works anywhere Ubuntu runs:
  <span>🖥️ LXD (local)</span><span>☁️ AWS EC2</span><span>☁️ Azure VM</span><span>☁️ DigitalOcean</span><span>💻 Multipass</span>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="usecase">
  <h4>💡 Example</h4>
  <p>You need a test web server for a teammate. Pick <b>Web server (nginx)</b>, paste their SSH key,
  download the file, launch. Two minutes later they log in and nginx is already running.
  Need five servers? Launch the same file five times.</p>
</div>
""",
    unsafe_allow_html=True,
)

# --- step 1: server type (outside the form so it can pre-fill the fields) ------------

st.subheader("What kind of server do you need?")
server_type = st.selectbox(
    "Server type",
    list(SERVER_TYPES),
    label_visibility="collapsed",
    help="Pick the closest match. It pre-fills the software list below; you can change anything.",
)
preset = SERVER_TYPES[server_type]

found = find_ssh_key()  # looks in ~/.ssh on the machine running this page

# --- step 2: the form ----------------------------------------------------------------

with st.form("server_form"):
    st.markdown("#### 👤 Login")
    col_a, col_b = st.columns([2, 1])
    username = col_a.text_input(
        "Username",
        value=getpass.getuser(),
        key="username",
        help="The name you log in with, e.g. alice. Lowercase, no spaces.",
    ).strip()
    col_b.write("")  # nudges the toggle down to line up with the text box
    sudo = col_b.toggle(
        "sudo without password",
        value=True,
        help="Keep ON. The user has no password (only an SSH key), so sudo cannot ask for one.",
    )

    st.markdown("#### 🔑 SSH public key")
    ssh_key = st.text_area(
        "Public key",
        value=found[1] if found else "",
        key="ssh_key",
        height=80,
        placeholder="ssh-ed25519 AAAA... you@laptop",
        help="Your only way to log in. Paste the contents of your .pub file, e.g. `cat ~/.ssh/id_ed25519.pub`. "
        "No key yet? Run `ssh-keygen -t ed25519`.",
    ).strip()
    if found:
        st.caption(f"Pre-filled from `{found[0]}`. Replace it to use a different key.")

    st.markdown("#### 🖥️ Server")
    col_c, col_d = st.columns(2)
    hostname = col_c.text_input(
        "Hostname (optional)",
        placeholder="web1",
        help="A short name for the server, e.g. web1. Letters, digits and dashes.",
    ).strip()
    timezone = col_d.selectbox(
        "Timezone",
        TIMEZONES,
        index=0,
        help="Start typing to search, e.g. America/St_Johns. Log times and cron jobs use this.",
    )

    st.markdown("#### 📦 Software")
    packages = st.multiselect(
        "Install these packages",
        options=sorted(set(SUGGESTED_SOFTWARE) | set(preset["packages"])),
        default=preset["packages"],
        accept_new_options=True,
        help="Pick from the list or type any Ubuntu package name and press Enter. Installed on first boot.",
    )
    runcmd_text = st.text_area(
        "Commands to run on first boot (optional)",
        value="\n".join(preset["runcmd"]),
        height=90,
        placeholder="systemctl enable --now nginx",
        help="One command per line, run once as root after packages are installed.",
    )

    st.markdown("#### ❤️ Monitoring")
    health = st.toggle(
        "Add an hourly health report",
        value=False,
        key="health",
        help="Installs a small script that logs disk, memory and service status to /var/log/health.log every hour.",
    )

    submitted = st.form_submit_button("⚡ Generate my file", type="primary", use_container_width=True)

# --- result ------------------------------------------------------------------------------

if submitted:
    problems = []
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
        problems.append("Username must be lowercase letters, digits, `-` or `_`.")
    if ssh_key and not ssh_key.startswith(("ssh-", "ecdsa-")):
        problems.append("That does not look like a public key. It should start with `ssh-ed25519` or `ssh-rsa`.")
    for p in problems:
        st.error(p)

    if not problems:
        opts = ServerOptions(
            username=username,
            passwordless_sudo=sudo,
            ssh_key=ssh_key or None,
            hostname=hostname or None,
            timezone=None if timezone == "UTC" else timezone,
            packages=[p.strip() for p in packages if p.strip()],
            runcmd=[line.strip() for line in runcmd_text.splitlines() if line.strip()],
            health=health,
        )
        st.session_state["result"] = (opts, to_yaml(build_config(opts)))

if "result" in st.session_state:
    opts, text = st.session_state["result"]

    st.subheader("✅ Your server will have")
    lines = [f"a user <b>{opts.username}</b>" + (" with password-free sudo" if opts.passwordless_sudo else "")]
    lines.append("SSH key login" if opts.ssh_key else "⚠️ <b>no SSH key</b>, you will not be able to log in")
    if opts.hostname:
        lines.append(f"hostname <b>{opts.hostname}</b>")
    if opts.timezone:
        lines.append(f"timezone <b>{opts.timezone}</b>")
    if opts.packages:
        lines.append("software: " + ", ".join(f"<code>{p}</code>" for p in opts.packages))
    if opts.runcmd:
        lines.append(f"{len(opts.runcmd)} first-boot command{'s' if len(opts.runcmd) != 1 else ''}")
    if opts.health:
        lines.append("an hourly health report in <code>/var/log/health.log</code>")
    st.markdown('<div class="card"><ul>' + "".join(f"<li>{l}</li>" for l in lines) + "</ul></div>", unsafe_allow_html=True)

    st.write("")
    try:
        validate_text(text)
        st.success("Checked: valid YAML, ready to use.")
    except ValueError as error:  # should never happen, but never hide it
        st.error(f"YAML problem: {error}")

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        tmp.write(text)
    schema = cloud_init_schema_check(Path(tmp.name))
    if schema is not None:
        st.code(schema, language=None)

    st.download_button(
        "⬇️  Download user-data.yaml",
        data=text,
        file_name="user-data.yaml",
        mime="text/yaml",
        type="primary",
        use_container_width=True,
    )

    with st.expander("See the file"):
        st.code(text, language="yaml")

    launch_steps = [
        lxd_launch_command(Path("user-data.yaml")),
        "sudo lxc exec test1 -- cloud-init status --wait",
        "sudo lxc list                      # find the IP",
        f"ssh {opts.username}@<ip>",
    ]
    if opts.health:
        launch_steps.append("sudo lxc exec test1 -- cat /var/log/health.log")
    launch_steps.append("sudo lxc delete --force test1      # clean up")

    with st.expander("How to use the file", expanded=True):
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
