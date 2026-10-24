"""Web UI for cloud-init-maker, built with Streamlit.

Run it with:   streamlit run app.py

Same questions as the command-line tool and the same builder underneath, so
both produce identical files. The page is written for someone who has never
heard of cloud-init: it explains the problem, walks through the questions in
small steps, and shows in plain English what the server will end up with.

Layout:
    hero (what / why)  ->  3 cards  ->  4-step strip
    left: questions in tabs          right: summary, download, YAML
"""

import getpass
import re
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

# --- styling ------------------------------------------------------------------
# A little CSS goes a long way. We only style our own HTML blocks (.hero, .card,
# .step) plus a few generic Streamlit containers, so Streamlit updates are safe.
st.markdown(
    """
<style>
  .block-container { padding-top: 1.5rem; max-width: 1200px; }
  #MainMenu, footer { visibility: hidden; }

  .hero { padding: 2.2rem 2.4rem; border-radius: 18px; color: white;
          background: linear-gradient(120deg, #1d4ed8 0%, #0ea5e9 100%); margin-bottom: 1.2rem; }
  .hero h1 { margin: 0 0 .4rem 0; font-size: 2.2rem; color: white; }
  .hero p  { margin: 0; font-size: 1.1rem; opacity: .95; max-width: 760px; }

  .card { background: white; border: 1px solid #e2e8f0; border-radius: 14px;
          padding: 1.1rem 1.2rem; height: 100%; }
  .card .icon { font-size: 1.6rem; }
  .card h4 { margin: .3rem 0 .4rem 0; font-size: 1.05rem; }
  .card p  { margin: 0; color: #475569; font-size: .95rem; line-height: 1.45; }

  .step { text-align: center; padding: .9rem .5rem; background: white;
          border: 1px solid #e2e8f0; border-radius: 12px; }
  .step .n { display: inline-block; width: 28px; height: 28px; line-height: 28px; border-radius: 50%;
             background: #2563eb; color: white; font-weight: 700; margin-bottom: .35rem; }
  .step b { display: block; font-size: .95rem; }
  .step span { color: #64748b; font-size: .85rem; }

  .why { background: #eff6ff; border-left: 4px solid #2563eb; padding: .55rem .8rem;
         border-radius: 8px; color: #1e3a8a; font-size: .9rem; margin: -.3rem 0 1rem 0; }

  .summary li { margin-bottom: .25rem; }
  div[data-testid="stTabs"] button { font-weight: 600; }
</style>
""",
    unsafe_allow_html=True,
)


def why(text: str) -> None:
    """A small blue note explaining why a question matters."""
    st.markdown(f'<div class="why">💡 {text}</div>', unsafe_allow_html=True)


# --- hero: what is this and why should I care? ---------------------------------

st.markdown(
    """
<div class="hero">
  <h1>☁️ cloud-init-maker</h1>
  <p>Describe the server you want. Download one small file. Launch an Ubuntu server
     that sets <b>itself</b> up on first boot: your user, your SSH key, your software,
     ready before you even log in.</p>
</div>
""",
    unsafe_allow_html=True,
)

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(
        """<div class="card"><div class="icon">😩</div><h4>The problem</h4>
        <p>Every new server starts empty. Creating a user, pasting a key, fixing permissions,
        installing packages… by hand, every time. Slow, boring, and one typo locks you out.</p></div>""",
        unsafe_allow_html=True,
    )
with c2:
    st.markdown(
        """<div class="card"><div class="icon">📄</div><h4>The solution</h4>
        <p>Ubuntu servers ship with <b>cloud-init</b>, which reads one YAML file on first boot
        and does all that setup. This page writes that file for you, with the tricky
        indentation always correct.</p></div>""",
        unsafe_allow_html=True,
    )
with c3:
    st.markdown(
        """<div class="card"><div class="icon">🚀</div><h4>The result</h4>
        <p>One file that works for a local LXD container, an AWS EC2 instance or an Azure VM.
        Launch ten servers that are all set up exactly the same way, in minutes.</p></div>""",
        unsafe_allow_html=True,
    )

st.write("")
s1, s2, s3, s4 = st.columns(4)
for col, n, title, sub in [
    (s1, 1, "Answer the questions", "on the left, each one explained"),
    (s2, 2, "Download the file", "user-data.yaml, checked for you"),
    (s3, 3, "Launch a server", "LXD, AWS or Azure"),
    (s4, 4, "Log in", "cloud-init already did the setup"),
]:
    col.markdown(
        f'<div class="step"><div class="n">{n}</div><b>{title}</b><span>{sub}</span></div>',
        unsafe_allow_html=True,
    )

st.write("")
st.divider()

left, right = st.columns([1.15, 1], gap="large")

# --- questions (left) ----------------------------------------------------------------

with left:
    st.subheader("Build your server")
    st.caption("Hover the ⓘ next to any field to see exactly what to type. Everything updates live on the right.")

    tab_login, tab_key, tab_server, tab_software, tab_health = st.tabs(
        ["👤 Login", "🔑 SSH key", "🖥️ Server", "📦 Software", "❤️ Health"]
    )

    with tab_login:
        why(
            "Ubuntu cloud images come with a generic <b>ubuntu</b> user. Creating your own user "
            "makes logins easy to recognise in logs and simple to hand out in a team."
        )
        username = st.text_input(
            "Username",
            value=getpass.getuser(),
            key="username",
            help="Type the name you will log in with, e.g. `alice`. Lowercase letters, digits, "
            "dashes or underscores. No spaces.",
        ).strip()
        if username and not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
            st.warning("Linux usernames are lowercase letters, digits, `-` and `_`, and cannot start with a digit.")

        sudo = st.toggle(
            "Allow `sudo` without a password",
            value=True,
            help="Leave ON for a personal or test server. Turn OFF only if you plan to set a password "
            "for this user yourself after the first login.",
        )
        why(
            "This user gets no password, only an SSH key. Without this switch, <code>sudo</code> would "
            "ask for a password that does not exist and you could not do admin tasks."
        )

    with tab_key:
        why(
            "Cloud servers turn <b>password login off</b>. Your <i>public</i> key is written into the "
            "server's <code>authorized_keys</code>; your <i>private</i> key stays on your computer. "
            "That pair is your only way in, so this is the most important question."
        )
        found = find_ssh_key()  # looks in ~/.ssh on the machine running this page
        choices = []
        if found:
            choices.append("Use the key found on this computer")
        choices += ["Paste a key", "Upload a .pub file", "No key"]
        key_choice = st.radio(
            "Where is your public key?",
            choices,
            help="Pick how to provide your key. Public keys end in `.pub` and start with `ssh-ed25519` or `ssh-rsa`. "
            "No key yet? Run `ssh-keygen -t ed25519` in a terminal to create one.",
        )

        ssh_key = None
        if found and key_choice == "Use the key found on this computer":
            st.caption(f"Found at `{found[0]}`")
            ssh_key = found[1]
            st.code(ssh_key, language=None)
        elif key_choice == "Paste a key":
            ssh_key = st.text_area(
                "Public key",
                placeholder="ssh-ed25519 AAAA... you@laptop",
                height=90,
                help="Open your `.pub` file (for example `cat ~/.ssh/id_ed25519.pub`), copy the whole line and paste it here.",
            ).strip() or None
        elif key_choice == "Upload a .pub file":
            uploaded = st.file_uploader(
                "Choose your .pub file",
                type=["pub"],
                help="Usually in the hidden `.ssh` folder in your home directory. Pick the file ending in `.pub`, never the one without.",
            )
            if uploaded:
                ssh_key = uploaded.read().decode().strip() or None
        else:
            st.error("Without a key you will not be able to log in to this server. Only pick this if you know what you are doing.")

        if ssh_key and not ssh_key.startswith(("ssh-", "ecdsa-")):
            st.warning("That does not look like a *public* key. Public keys start with `ssh-ed25519`, `ssh-rsa` or `ecdsa-`.")

    with tab_server:
        why("Both optional. Leave them blank and Ubuntu picks sensible defaults.")
        hostname = st.text_input(
            "Hostname",
            placeholder="web1",
            help="A short name for this server, e.g. `web1` or `db-test`. Letters, digits and dashes. "
            "You will see it in your terminal prompt and in logs.",
        ).strip() or None
        timezone = st.text_input(
            "Timezone",
            placeholder="America/St_Johns",
            help="A timezone name in `Region/City` form, e.g. `America/St_Johns`, `Europe/London`, `Asia/Kolkata`. "
            "Leave empty for UTC.",
        ).strip() or None
        why("A hostname tells servers apart when you have many. A timezone makes log times and cron jobs match your clock.")

    with tab_software:
        why("Everything here runs during the first boot, so the server is ready the moment you log in.")
        packages = split_csv(
            st.text_input(
                "Packages to install",
                placeholder="nginx, git, htop",
                help="Names of Ubuntu packages, separated by commas, exactly as you would type after `apt install`.",
            )
        )
        runcmd_text = st.text_area(
            "Commands to run on first boot",
            placeholder="systemctl enable --now nginx\necho hello > /root/hello.txt",
            height=110,
            help="One shell command per line. They run once, as root, after the packages are installed. "
            "Good for enabling a service, cloning a repo or writing a config file.",
        )
        runcmd = [line.strip() for line in runcmd_text.splitlines() if line.strip()]

    with tab_health:
        health = st.toggle(
            "Add the hourly health checker",
            value=False,
            key="health",
            help="Turn ON to install a small script that writes disk, memory and service status to "
            "/var/log/health.log every hour.",
        )
        why(
            "A tiny Python script is placed at <code>/opt/health/health.py</code> and run by cron every hour. "
            "It records disk usage, memory usage and whether <code>cron</code> is running, so you spot a "
            "filling disk <b>before</b> it becomes an outage."
        )
        st.markdown(
            "Optional AI: if the environment variable `GROQ_API_KEY` is set on the server and the `openai` "
            "package is installed, each report also gets a two-sentence plain-English explanation. "
            "No key, no AI, just the numbers. Keys are never written into the file."
        )

# --- result (right) --------------------------------------------------------------------

opts = ServerOptions(
    username=username or getpass.getuser(),
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
    st.subheader("Your server will have")

    def item(ok: bool, label: str) -> str:
        return f"<li>{'✅' if ok else '⚠️'} {label}</li>"

    summary = [
        item(True, f"a user called <b>{opts.username}</b>" + (" with password-free <code>sudo</code>" if sudo else " (sudo asks for a password)")),
        item(bool(ssh_key), "SSH key login" if ssh_key else "<b>no SSH key</b>: you cannot log in"),
    ]
    if hostname:
        summary.append(item(True, f"hostname <b>{hostname}</b>"))
    if timezone:
        summary.append(item(True, f"timezone <b>{timezone}</b>"))
    if packages:
        summary.append(item(True, f"{len(packages)} package{'s' if len(packages) != 1 else ''}: " + ", ".join(f"<code>{p}</code>" for p in packages)))
    if runcmd:
        summary.append(item(True, f"{len(runcmd)} first-boot command{'s' if len(runcmd) != 1 else ''}"))
    if health:
        summary.append(item(True, "an hourly health report in <code>/var/log/health.log</code>"))
    st.markdown(f'<div class="card"><ul class="summary">{"".join(summary)}</ul></div>', unsafe_allow_html=True)

    st.write("")

    # Validate exactly like the CLI does: re-load, then cloud-init schema if present.
    try:
        validate_text(text)
        st.success("Checked: valid YAML, starts with `#cloud-config`, key is inside the user block.")
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
        help="Saves the file to your Downloads folder. Use it with the launch command below.",
    )

    with st.expander("👀 See the generated file", expanded=False):
        st.code(text, language="yaml")

    launch_steps = [
        lxd_launch_command(Path("user-data.yaml")),
        "sudo lxc exec test1 -- cloud-init status --wait",
        "sudo lxc list                      # find the IP",
        f"ssh {opts.username}@<ip>",
    ]
    if health:
        launch_steps.append("sudo lxc exec test1 -- cat /var/log/health.log")
    launch_steps.append("sudo lxc delete --force test1      # clean up when done")

    with st.expander("🚀 Next: launch a server with it", expanded=True):
        st.markdown(
            f"""
**On your Ubuntu machine with LXD** (install once: `sudo snap install lxd && sudo lxd init --minimal`)

```bash
{chr(10).join(launch_steps)}
```

**On AWS or Azure:** paste the same file into the **User data** (AWS) or **Custom data** (Azure)
box when you create the instance.

**Changed something?** cloud-init only runs on the *first* boot, so launch a fresh server.
            """
        )

st.divider()
st.caption(
    "Open source, MIT licence. Code, tests and a command-line version at "
    "[github.com/JasleenMinhas578/cloud-init-maker](https://github.com/JasleenMinhas578/cloud-init-maker)."
)
