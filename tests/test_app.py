"""Smoke test for the Streamlit page: it must render without errors and
produce the same YAML as the builder. Skipped if streamlit is not installed."""

from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402  (import after the skip check)

from cloud_init_maker.builder import ServerOptions, build_config, to_yaml  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyExampleKeyExampleKeyExampleKe alice@laptop"


def shown_yaml(app):
    return [block.value for block in app.code if block.value.startswith("#cloud-config")]


def test_page_renders_with_an_example_preview():
    app = AppTest.from_file(APP).run()
    assert not app.exception
    page_text = " ".join(block.value for block in app.markdown)
    assert "cloud-init-maker" in page_text
    # Before anything is typed, the preview uses the example name, not the real user.
    assert "name: alice" in shown_yaml(app)[0]


def test_preview_matches_the_builder_as_you_type():
    app = AppTest.from_file(APP).run()
    app.text_input("username").set_value("bob")
    app.text_area("ssh_key").set_value(KEY)
    app.toggle("health").set_value(True).run()
    assert not app.exception

    expected = to_yaml(build_config(ServerOptions(username="bob", ssh_key=KEY, health=True)))
    assert shown_yaml(app)[0].strip() == expected.strip()  # the code block drops the final newline
