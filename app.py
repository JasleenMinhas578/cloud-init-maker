"""Web UI for cloud-init-maker, built with Streamlit.

Run it with:   streamlit run app.py

Same questions as the command-line tool and the same builder underneath, so
both produce identical files. The page also explains *why* each setting
matters, for people who are new to cloud-init. The YAML on the right updates
live as you change answers on the left.
"""

import getpass
import tempfile
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

st.set_page_config(page_title="cloud-init-maker", page_icon="☁️", layout="wide")

# --- intro ------------------------------------------------------------------

st.title("☁️ cloud-init-maker")
st.write(
    "Answer a few questions, download a ready-to-use **user-data.yaml**, and launch "
    "an Ubuntu server that sets itself up on first boot: your user, your SSH key, "
    "your packages, all done before you log in for the first time."
)

with st.expander("New here? What is cloud-init and why does this help?"):
    st.markdown(
        """
**The problem.** Every new server starts empty. Setting it up by hand means
creating a user, pasting an SSH key, fixing file permissions, installing packages,
adding cron jobs... and doing it all again for the next server. It is slow, and
one typo can lock you out.

**cloud-init** is a program already included in Ubuntu cloud images. On the very
first boot it reads one YAML file (called *user-data*) and does all of that setup
for you. The same file works for a local LXD container, an AWS EC2 instance or an
Azure VM.

**This tool** writes that file. It builds the config as structured data and lets a
YAML library print it, so the indentation is right every time (putting the SSH key
at the wrong level is the classic mistake that causes `Permission denied`).

```
You answer questions  →  download user-data.yaml  →  LXD / cloud starts server  →  cloud-init sets it up
```
        """
    )

left, right = st.columns([1, 1], gap="large")

# --- questions (left column) --------------------------------------------------

with left:
    st.subheader("1. Your login")

    username = st.text_input(
        "Username",
        value=getpass.getuser(),
        key="username",
        help="The Linux user created on the server. You will log in as this user.",
    )
    st.caption(
        "Why: Ubuntu cloud images come with a generic `ubuntu` user. "
        "Your own user is easier to recognise in logs and to manage in a team."
    )

    sudo = st.checkbox(
        "Sudo without a password",
        value=True,
        help="Lets this user run admin commands with `sudo` without typing a password.",
    )
    st.caption(
        "Why: the user has no password at all (only an SSH key), so without this, "
        "`sudo` would ask for a password that does not exist."
    )

    st.subheader("2. SSH public key")
    st.caption(
        "Why: cloud servers turn off password login. Your *public* key is placed in "
        "the server's `authorized_keys`, your *private* key stays on your computer, "
        "and that pair is how you get in. No key means no way to log in."
    )

    found = find_ssh_key()  # looks in ~/.ssh on the machine running this page
    choices = []
    if found:
        choices.append(f"Use the key found at {found[0]}")
    choices += ["Paste a key", "Upload a .pub file", "No key (not recommended)"]
    key_choice = st.radio("Where is your key?", choices, label_visibility="collapsed")

    ssh_key = None
    if found and key_choice == choices[0]:
        ssh_key = found[1]
        st.code(ssh_key, language=None)
    elif key_choice == "Paste a key":
        ssh_key = st.text_area(
            "Public key", placeholder="ssh-ed25519 AAAA... you@laptop", height=80
        ).strip() or None
    elif key_choice == "Upload a .pub file":
        uploaded = st.file_uploader("Choose your .pub file", type=["pub"])
        if uploaded:
            ssh_key = uploaded.read().decode().strip() or None

    if ssh_key and not ssh_key.startswith(("ssh-", "ecdsa-")):
        st.warning("That does not look like a public key. Public keys start with `ssh-ed25519`, `ssh-rsa`, ...")

    st.subheader("3. Server identity (optional)")
    hostname = st.text_input(
        "Hostname",
        placeholder="web1",
        help="The name the server gives itself. Leave empty to keep the default.",
    ).strip() or None
    st.caption("Why: with many servers, a clear name in your prompt and logs saves confusion.")

    timezone = st.text_input(
        "Timezone",
        placeholder="America/St_Johns",
        help="A name from the tz database, e.g. Europe/London or Asia/Kolkata.",
    ).strip() or None
    st.caption("Why: log timestamps and cron jobs will match your local time instead of UTC.")

    st.subheader("4. Software and first-boot commands (optional)")
    packages = split_csv(
        st.text_input(
            "Packages to install",
            placeholder="nginx, git, htop",
            help="Comma-separated apt package names.",
        )
    )
    st.caption("Why: installed during first boot, so the server is ready to use the moment you log in.")

    runcmd_text = st.text_area(
        "Commands to run on first boot",
        placeholder="systemctl enable nginx\necho hello > /root/hello.txt",
        height=100,
        help="One command per line. They run once, as root, after packages are installed.",
    )
    runcmd = [line.strip() for line in runcmd_text.splitlines() if line.strip()]
    st.caption("Why: anything the other options cannot express, e.g. enabling a service or cloning a repo.")

    st.subheader("5. Health checker (optional)")
    health = st.checkbox("Include the hourly server health checker", value=False, key="health")
    st.caption(
        "Why: a tiny Python script is placed at `/opt/health/health.py` and run by cron "
        "every hour. It appends disk usage, memory usage and service status to "
        "`/var/log/health.log`, so you can spot a full disk before it becomes an outage. "
        "If `GROQ_API_KEY` is set on the server it also adds a two-sentence AI explanation."
    )

# --- result (right column) ------------------------------------------------------

opts = ServerOptions(
    username=username.strip() or getpass.getuser(),
    passwordless_sudo=sudo,
    ssh_key=ssh_key,
    hostname=hostname,
    timezone=timezone,
    packages=packages,
    runcmd=runcmd,
    health=health,
)
text = to_yaml(build_config(opts))

with right:
    st.subheader("Your user-data.yaml")

    # Validate exactly like the CLI does: re-load, then cloud-init schema if present.
    try:
        validate_text(text)
        st.success("Valid YAML, starts with `#cloud-config`.")
    except ValueError as error:  # should never happen, but never hide it
        st.error(f"YAML problem: {error}")

    if not ssh_key:
        st.warning("No SSH key: you will not be able to log in to this server.")

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp:
        tmp.write(text)
    schema = cloud_init_schema_check(Path(tmp.name))
    if schema is None:
        st.info("`cloud-init` is not installed on this computer, so the schema check was skipped. It runs automatically in the project's GitHub Actions.")
    else:
        st.code(schema, language=None)

    st.download_button(
        "⬇️ Download user-data.yaml",
        data=text,
        file_name="user-data.yaml",
        mime="text/yaml",
        type="primary",
        use_container_width=True,
    )

    st.code(text, language="yaml")

    with st.expander("Next: launch a server with it (LXD on Ubuntu)"):
        st.markdown(
            f"""
1. Install LXD once: `sudo snap install lxd` then `sudo lxd init --minimal`
2. Launch a container with your file:
```bash
{lxd_launch_command(Path("user-data.yaml"))}
```
3. Wait for cloud-init: `sudo lxc exec test1 -- cloud-init status --wait`
4. Get the IP with `sudo lxc list`, then `ssh {opts.username}@<ip>`
{"5. See the health log: `sudo lxc exec test1 -- cat /var/log/health.log`" if health else ""}
6. Clean up: `sudo lxc delete --force test1`

On AWS or Azure, paste the same file into the **User data** / **Custom data**
box when creating the instance.
            """
        )
