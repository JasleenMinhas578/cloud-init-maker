"""Web UI for cloud-init-maker, built with Streamlit.

Run it with:   streamlit run app.py

Same builder as the command-line tool, so both produce identical files.

Layout:
    header (what it is, where the file is used)
    left:  the form (server type, login, SSH key, server, software, monitoring)
    right: the file, updating live as you type, Download, and launch steps
           for the platform you pick (LXD, AWS, Azure, DigitalOcean, Multipass)
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

PLATFORMS = ["LXD (local)", "AWS EC2", "Azure VM", "DigitalOcean", "Multipass"]

# --- styling -------------------------------------------------------------------------

st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  /* Text elements only. Never use "*" here: it would also override Streamlit's icon font. */
  .stApp :is(p, h1, h2, h3, h4, li, a, label, input, textarea, summary, div[data-testid="stMarkdownContainer"]) {
    font-family: 'Inter', system-ui, sans-serif;
  }
  .block-container { padding-top: 1.2rem; max-width: 1250px; }
  #MainMenu, footer { visibility: hidden; }

  /* header */
  .hero { padding: 1.8rem 2rem; border-radius: 18px; color: white; text-align: center;
          background: linear-gradient(120deg, #1e3a8a 0%, #2563eb 55%, #0891b2 100%);
          box-shadow: 0 10px 40px rgba(37, 99, 235, .35); }
  .hero h1 { margin: 0; font-size: 2.3rem; font-weight: 700; color: white; letter-spacing: -.5px; }
  .hero p  { margin: .4rem 0 0 0; font-size: 1.1rem; opacity: .95; }
  .hero .flow { margin-top: .9rem; font-size: .95rem; opacity: .9; }
  .hero .flow b { background: rgba(255,255,255,.18); padding: .25rem .6rem; border-radius: 999px; margin: 0 .15rem; font-weight: 600; }
  .pills { text-align: center; margin: .6rem 0 1.2rem 0; color: #94a3b8; font-size: .9rem; }
  .pills span { display: inline-block; background: #141d2e; border: 1px solid #263349; border-radius: 999px;
                padding: .3rem .8rem; margin: .2rem; color: #e5e7eb; }

  /* form */
  div[data-testid="stVerticalBlockBorderWrapper"] { background: #141d2e; border-radius: 16px; padding: .4rem .6rem; }
  .section { display: flex; align-items: center; gap: .6rem; font-size: 1.15rem; font-weight: 700; color: #f1f5f9;
             margin: 1.4rem 0 .5rem 0; padding-top: 1.1rem; border-top: 1px solid #263349; }
  .section.first { border-top: none; padding-top: .2rem; margin-top: .2rem; }
  .section .num { display: inline-flex; width: 26px; height: 26px; border-radius: 50%; background: #3b82f6; color: white;
                  font-size: .85rem; font-weight: 700; align-items: center; justify-content: center; flex: none; }
  .hint { color: #94a3b8; font-size: .9rem; line-height: 1.6; margin: -.45rem 0 1rem 0; }
  .hint code { background: #0b1220; color: #e5e7eb; padding: .1rem .4rem; border-radius: 5px; font-size: .85em; white-space: nowrap; }
  div[data-testid="stWidgetLabel"] p { font-size: .95rem; font-weight: 600; color: #e5e7eb; }

  /* result */
  .card { background: #141d2e; border: 1px solid #263349; border-radius: 14px; padding: .9rem 1.2rem; }
  .card b.title { display: block; margin-bottom: .3rem; color: #f1f5f9; }
  .card ul { margin: 0; padding-left: 1.2rem; }
  .card li { margin-bottom: .2rem; line-height: 1.5; }
  .card code { background: #0b1220; padding: .1rem .35rem; border-radius: 5px; font-size: .85em; }
</style>
""",
    unsafe_allow_html=True,
)


def section(number: int, title: str, first: bool = False) -> None:
    cls = "section first" if first else "section"
    st.markdown(f'<div class="{cls}"><span class="num">{number}</span>{title}</div>', unsafe_allow_html=True)


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
<div class="pills">The same file works on:
  <span>🖥️ LXD (local)</span><span>☁️ AWS EC2</span><span>☁️ Azure VM</span><span>☁️ DigitalOcean</span><span>💻 Multipass</span>
</div>
""",
    unsafe_allow_html=True,
)

left, right = st.columns([1, 1], gap="large")

# --- the form (left) ----------------------------------------------------------------------

with left:
    with st.container(border=True):
        section(1, "What kind of server?", first=True)
        server_type = st.selectbox("Server type", list(SERVER_TYPES), label_visibility="collapsed")
        hint("Pick the closest match. It fills in the software below. You can change anything.")
        preset = SERVER_TYPES[server_type]

        section(2, "Your login")
        username = st.text_input("Username", placeholder=f"for example: {EXAMPLE_USER}", key="username").strip()
        hint("The name you will type when you log in. Lowercase letters and digits, no spaces.")
        if username and not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
            st.warning("Usernames use lowercase letters, digits, - and _, and cannot start with a digit.")
        sudo = st.toggle("Allow admin commands (sudo) without a password", value=True)
        hint("Keep this on. The user has no password, only a key, so sudo could not ask for one.")

        section(3, "Your SSH public key")
        hint("This is how you log in. Paste the one line of text from your <code>.pub</code> file.<br>"
             "To see it, run <code>cat ~/.ssh/id_ed25519.pub</code><br>"
             "No key yet? Run <code>ssh-keygen -t ed25519</code>")
        found = find_ssh_key()  # looks in ~/.ssh on the machine running this page
        use_found = False
        if found:
            use_found = st.checkbox(f"Use the key found on this computer ({found[0].name})", value=False)
        ssh_key = st.text_area(
            "Public key",
            key="ssh_key",
            height=80,
            placeholder="ssh-ed25519 AAAA…  (one long line)",
            disabled=use_found,
            label_visibility="collapsed",
        ).strip()
        if use_found:
            ssh_key = found[1]
        if ssh_key and not ssh_key.startswith(("ssh-", "ecdsa-")):
            st.warning("That does not look like a public key. It should start with ssh-ed25519 or ssh-rsa.")

        section(4, "Server details")
        c1, c2 = st.columns(2)
        hostname = c1.text_input("Hostname (optional)", placeholder="for example: web1").strip()
        timezone = c2.selectbox("Timezone", TIMEZONES, index=0)
        hint("Hostname is a short name for the server. Timezone: click and type to search, for example America/St_Johns.")

        section(5, "Software to install")
        packages = st.multiselect(
            "Packages",
            options=sorted(set(SUGGESTED_SOFTWARE) | set(preset["packages"])),
            default=preset["packages"],
            accept_new_options=True,
            label_visibility="collapsed",
            placeholder="Choose from the list, or type a package name and press Enter",
        )
        hint("Any Ubuntu package name works, the same name you would give to apt install.")
        runcmd_text = st.text_area(
            "Commands to run once on first boot (optional)",
            value="\n".join(preset["runcmd"]),
            height=80,
            placeholder="for example: systemctl enable --now nginx",
        )
        hint("One command per line. They run as root after the software is installed.")

        section(6, "Monitoring")
        health = st.toggle("Add an hourly health report (optional)", value=False, key="health")
        hint("A small script records disk, memory and service status every hour in a log file on the server.")

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
ready = bool(username and ssh_key)


def launch_instructions(platform: str, user: str, health: bool) -> str:
    """Markdown with the exact steps for the chosen platform."""
    log_hint = "\n\nHealth report: `cat /var/log/health.log` on the server." if health else ""
    after = "cloud-init runs on the **first boot only**. Changed the file? Launch a fresh server."

    if platform == "LXD (local)":
        return f"""
**On an Ubuntu machine** (install LXD once: `sudo snap install lxd && sudo lxd init --minimal`)
```bash
{lxd_launch_command(Path("user-data.yaml"))}
sudo lxc exec test1 -- cloud-init status --wait
sudo lxc list                      # find the IP
ssh {user}@<ip>
sudo lxc delete --force test1      # clean up when done
```{log_hint}

{after}"""

    if platform == "AWS EC2":
        return f"""
**In the AWS console**
1. EC2 → **Launch instance** → choose an **Ubuntu Server 24.04** image.
2. Pick a key pair and a security group that allows **SSH (port 22)**.
3. Open **Advanced details** → scroll to **User data** → paste the whole file.
4. Launch, then: `ssh {user}@<public-ip>`

**Or with the AWS CLI**
```bash
aws ec2 run-instances --image-id <ubuntu-24.04-ami-id> --instance-type t3.micro \\
  --key-name <your-key-pair> --security-group-ids <sg-with-port-22> \\
  --user-data file://user-data.yaml
```{log_hint}

{after}"""

    if platform == "Azure VM":
        return f"""
**In the Azure portal**
1. **Create a resource** → **Virtual machine** → image **Ubuntu Server 24.04 LTS**.
2. Authentication: **SSH public key**, username **{user}**, and allow **SSH (22)** in inbound ports.
3. Open the **Advanced** tab → **Custom data** → paste the whole file.
4. Create, then: `ssh {user}@<public-ip>`

**Or with the Azure CLI**
```bash
az vm create --resource-group <your-group> --name test1 --image Ubuntu2404 \\
  --admin-username {user} --ssh-key-values ~/.ssh/id_ed25519.pub \\
  --custom-data user-data.yaml
```{log_hint}

{after}"""

    if platform == "DigitalOcean":
        return f"""
**In the DigitalOcean dashboard**
1. **Create** → **Droplets** → image **Ubuntu 24.04**.
2. Authentication: **SSH key**.
3. Open **Advanced options** → tick **Add initialization scripts (free)** → paste the whole file.
4. Create, then: `ssh {user}@<droplet-ip>`

**Or with doctl**
```bash
doctl compute droplet create test1 --image ubuntu-24-04-x64 --size s-1vcpu-1gb \\
  --region nyc1 --ssh-keys <your-key-id> --user-data-file user-data.yaml
```{log_hint}

{after}"""

    return f"""
**On any Mac, Windows or Linux machine with Multipass** (`https://multipass.run`)
```bash
multipass launch 24.04 --name test1 --cloud-init user-data.yaml
multipass info test1               # find the IP
ssh {user}@<ip>
multipass delete --purge test1     # clean up when done
```{log_hint}

{after}"""


with right:
    st.subheader("Your file: user-data.yaml")
    st.caption(
        f"Updates as you type. Showing the example name **{EXAMPLE_USER}** until you enter yours."
        if not username else "Updates as you type."
    )

    lines = [f"creates the user <b>{opts.username}</b>" + (" with password-free sudo" if sudo else "")]
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
    st.markdown(
        '<div class="card"><b class="title">When the server starts, this file:</b><ul>'
        + "".join(f"<li>{l}</li>" for l in lines) + "</ul></div>",
        unsafe_allow_html=True,
    )
    st.write("")

    st.download_button(
        "⬇️  Download user-data.yaml",
        data=text,
        file_name="user-data.yaml",
        mime="text/yaml",
        type="primary",
        use_container_width=True,
        disabled=not ready,
        help=None if ready else "Fill in a username and an SSH key first.",
    )
    if not ready:
        st.caption("Enter a username and an SSH key to enable the download.")

    try:
        validate_text(text)
    except ValueError as error:  # should never happen, but never hide it
        st.error(f"YAML problem: {error}")
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        tmp.write(text)
    schema = cloud_init_schema_check(Path(tmp.name))
    if schema is not None:
        st.code(schema, language=None)

    with st.expander("See the file", expanded=True):
        st.code(text, language="yaml")

    st.subheader("Where will you run it?")
    platform = st.segmented_control("Platform", PLATFORMS, default=PLATFORMS[0], label_visibility="collapsed")
    st.markdown(launch_instructions(platform or PLATFORMS[0], opts.username, health))

st.divider()
st.caption(
    "Open source, MIT licence. Code, tests and a command-line version: "
    "[github.com/JasleenMinhas578/cloud-init-maker](https://github.com/JasleenMinhas578/cloud-init-maker)"
)
