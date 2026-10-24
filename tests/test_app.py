"""Smoke test for the Streamlit page: it must render without errors and
produce the same YAML as the builder. Skipped if streamlit is not installed."""

from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402  (import after the skip check)

from cloud_init_maker.builder import ServerOptions, build_config, to_yaml  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyExampleKeyExampleKeyExampleKe alice@laptop"


def test_page_renders_without_exceptions():
    app = AppTest.from_file(APP).run()
    assert not app.exception
    page_text = " ".join(block.value for block in app.markdown)
    assert "cloud-init-maker" in page_text
    assert "Example" in page_text  # the use-case box is there


def test_submitting_the_form_shows_yaml_that_matches_the_builder():
    app = AppTest.from_file(APP).run()
    app.text_input("username").set_value("alice")
    app.text_area("ssh_key").set_value(KEY)
    app.toggle("health").set_value(True)
    app.button[0].click().run()  # the form's "Generate" button
    assert not app.exception

    shown = [block.value for block in app.code if block.value.startswith("#cloud-config")]
    assert shown, "the page should show the generated YAML after submit"

    expected = to_yaml(build_config(ServerOptions(username="alice", ssh_key=KEY, health=True)))
    assert shown[0].strip() == expected.strip()  # the code block drops the final newline
