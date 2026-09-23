from __future__ import annotations

import json

import pytest

from nier.errors import ProtocolError
from nier.protocol import UiDump, UiSource
from nier.ui import UiDocument, parse_uidump

UI_XML = """
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" clickable="false">
    <node class="android.widget.Button" text="登录"
          resource-id="com.example:id/login" content-desc="登录按钮"
          bounds="[10,20][210,120]" clickable="true" visible-to-user="true" />
    <node class="android.widget.TextView" text="设置" visible-to-user="false" />
  </node>
</hierarchy>
"""


def test_parse_android_ui_xml_and_find_nodes() -> None:
    document = parse_uidump(UI_XML, source=UiSource.UIAUTOMATOR)

    assert isinstance(document, UiDocument)
    login = document.find(resource_id="com.example:id/login")
    assert login is not None
    assert login.text == "登录"
    assert login.text_content == "登录"
    assert login.class_name == "android.widget.Button"
    assert login.content_desc == "登录按钮"
    assert login.bounds == (10, 20, 210, 120)
    assert login.center == (110.0, 70.0)
    assert login.clickable is True
    assert login.visible is True

    assert document.find(text="设置", visible=True) is None
    assert document.find(text_contains="登", clickable=True) is login
    assert len(document.find_all(class_name="android.widget.Button")) == 1


def test_parse_webview_html_and_read_file(tmp_path) -> None:
    html = '<html><body><button id="login" aria-label="Login">Log in</button></body></html>'
    path = tmp_path / "ui.html"
    path.write_text(html, encoding="utf-8")

    document = parse_uidump(path, source=UiSource.WEBVIEW_DEVTOOLS)
    button = document.find(tag="button")

    assert button is not None
    assert button.resource_id == "login"
    assert button.content_desc == "Login"
    assert button.text_content == "Log in"


def test_parse_uidump_preserves_dump_metadata() -> None:
    dump = UiDump(
        "<hierarchy />",
        UiSource.UIAUTOMATOR_FALLBACK,
        complete=False,
        warning="webview unavailable",
    )

    document = parse_uidump(dump)

    assert document.source is UiSource.UIAUTOMATOR_FALLBACK
    assert document.complete is False
    assert document.warning == "webview unavailable"


def test_ui_document_can_be_serialized_as_bounded_structure() -> None:
    document = parse_uidump(UI_XML, source=UiSource.UIAUTOMATOR)

    structured = document.to_dict(max_nodes=10)
    login = structured["root"]["children"][0]["children"][0]  # type: ignore[index]

    assert structured["source"] == "UIAUTOMATOR"
    assert login["text"] == "登录"  # type: ignore[index]
    assert login["resource_id"] == "com.example:id/login"  # type: ignore[index]
    assert login["bounds"] == [10, 20, 210, 120]  # type: ignore[index]
    assert login["center"] == [110.0, 70.0]  # type: ignore[index]
    json.dumps(structured, ensure_ascii=False)


def test_ui_document_structure_can_be_bounded() -> None:
    document = parse_uidump(UI_XML)

    structured = document.to_dict(max_nodes=2)

    assert structured["root"]["children"][0]["children"][0]["truncated"] is True  # type: ignore[index]


@pytest.mark.parametrize("value", ["", "not markup"])
def test_parse_uidump_rejects_empty_or_unparseable_content(value: str) -> None:
    with pytest.raises(ProtocolError):
        parse_uidump(value)
