"""Tests for builder.py: the part that turns answers into a cloud-init config."""

import yaml

from cloud_init_maker.builder import (
    HEALTH_CRON,
    HEALTH_SCRIPT,
    ServerOptions,
    build_config,
    lxd_launch_command,
    to_yaml,
    validate_text,
)

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyExampleKeyExampleKeyExampleKe alice@laptop"


def basic_options(**overrides):
    """A small helper so each test only spells out what it cares about."""
    values = dict(username="alice", ssh_key=KEY)
    values.update(overrides)
    return ServerOptions(**values)


# --- user block ---------------------------------------------------------------


def test_user_block_has_name_shell_and_sudo_group():
    config = build_config(basic_options())
    user = config["users"][0]
    assert user["name"] == "alice"
    assert user["shell"] == "/bin/bash"
    assert "sudo" in user["groups"]


def test_passwordless_sudo_on_by_default():
    user = build_config(basic_options())["users"][0]
    assert user["sudo"] == "ALL=(ALL) NOPASSWD:ALL"


def test_passwordless_sudo_can_be_turned_off():
    user = build_config(basic_options(passwordless_sudo=False))["users"][0]
    assert "sudo" not in user


# --- SSH key placement --------------------------------------------------------


def test_ssh_key_sits_inside_the_user_entry():
    config = build_config(basic_options())
    assert config["users"][0]["ssh_authorized_keys"] == [KEY]
    # The common mistake is putting it at the top level. Make sure we do not.
    assert "ssh_authorized_keys" not in config


def test_ssh_key_is_indented_under_the_user_in_the_yaml_text():
    text = to_yaml(build_config(basic_options()))
    lines = text.splitlines()
    header = next(line for line in lines if "ssh_authorized_keys:" in line)
    key_line = next(line for line in lines if line.strip() == f"- {KEY}")

    def indent(line):
        return len(line) - len(line.lstrip())

    # "users:" is at column 0, the user's fields are indented under it,
    # and the key is indented further under ssh_authorized_keys.
    assert "users:" in lines
    assert indent(header) > 0
    assert indent(key_line) > indent(header)


def test_no_ssh_key_means_no_ssh_authorized_keys_field():
    user = build_config(basic_options(ssh_key=None))["users"][0]
    assert "ssh_authorized_keys" not in user


# --- hostname, timezone, packages, runcmd ---------------------------------------


def test_hostname_and_timezone_are_optional():
    config = build_config(basic_options())
    assert "hostname" not in config
    assert "timezone" not in config

    config = build_config(basic_options(hostname="web1", timezone="America/St_Johns"))
    assert config["hostname"] == "web1"
    assert config["manage_etc_hosts"] is True
    assert config["timezone"] == "America/St_Johns"


def test_packages_are_listed_and_apt_update_is_turned_on():
    config = build_config(basic_options(packages=["nginx", "git"]))
    assert config["packages"] == ["nginx", "git"]
    assert config["package_update"] is True


def test_no_packages_means_no_packages_section():
    config = build_config(basic_options())
    assert "packages" not in config
    assert "package_update" not in config


def test_runcmd_keeps_order():
    config = build_config(basic_options(runcmd=["echo one", "echo two"]))
    assert config["runcmd"] == ["echo one", "echo two"]


# --- health checker -----------------------------------------------------------


def test_health_option_adds_script_cron_and_python():
    config = build_config(basic_options(health=True))

    paths = [entry["path"] for entry in config["write_files"]]
    assert HEALTH_SCRIPT in paths
    assert HEALTH_CRON in paths

    script = next(e for e in config["write_files"] if e["path"] == HEALTH_SCRIPT)
    assert script["permissions"] == "0755"
    assert "def memory_percent" in script["content"]  # the real template was read

    cron = next(e for e in config["write_files"] if e["path"] == HEALTH_CRON)
    assert "0 * * * *" in cron["content"]
    assert "/var/log/health.log" in cron["content"]

    assert "python3" in config["packages"]
    assert "python3-venv" in config["packages"]
    assert any("health.py" in cmd for cmd in config["runcmd"])


def test_health_off_by_default():
    config = build_config(basic_options())
    assert "write_files" not in config


def test_health_does_not_duplicate_python3():
    config = build_config(basic_options(health=True, packages=["python3", "git"]))
    assert config["packages"].count("python3") == 1


# --- YAML validity ------------------------------------------------------------


def test_yaml_starts_with_cloud_config_header():
    text = to_yaml(build_config(basic_options()))
    assert text.splitlines()[0] == "#cloud-config"


def test_yaml_round_trips_back_to_the_same_dict():
    config = build_config(basic_options(health=True, packages=["git"], runcmd=["echo hi"]))
    text = to_yaml(config)
    assert yaml.safe_load(text) == config
    assert validate_text(text) == config


def test_long_ssh_key_is_not_wrapped_over_several_lines():
    text = to_yaml(build_config(basic_options()))
    assert f"- {KEY}" in text


def test_validate_text_rejects_missing_header():
    try:
        validate_text("users: []\n")
    except ValueError as error:
        assert "#cloud-config" in str(error)
    else:
        raise AssertionError("expected a ValueError")


def test_lxd_command_mentions_the_file():
    command = lxd_launch_command("user-data.yaml")
    assert "lxc launch ubuntu:24.04" in command
    assert 'user.user-data="$(cat user-data.yaml)"' in command
