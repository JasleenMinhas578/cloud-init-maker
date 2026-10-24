"""Smoke test for the Streamlit page: it must render without errors and
produce the same YAML as the builder. Skipped if streamlit is not installed."""

from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402  (import after the skip check)

from cloud_init_maker.builder import ServerOptions, build_config, to_yaml  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_page_renders_without_exceptions():
    app = AppTest.from_file(APP).run()
    assert not app.exception
    assert "cloud-init-maker" in app.title[0].value


def test_page_yaml_matches_the_builder():
    app = AppTest.from_file(APP).run()
    app.text_input("username").set_value("alice").run()
    app.checkbox("health").check().run()
    assert not app.exception

    shown = [block.value for block in app.code if block.value.startswith("#cloud-config")]
    assert shown, "the page should show the generated YAML"

    # Whatever SSH key the page picked up, the builder must agree with the page.
    chosen_key = None
    for block in app.code:
        if block.value.startswith(("ssh-", "ecdsa-")):
            chosen_key = block.value
    expected = to_yaml(build_config(ServerOptions(username="alice", ssh_key=chosen_key, health=True)))
    assert shown[0].strip() == expected.strip()  # the code block drops the final newline
