"""Render a captured Android Intent as a reusable Nier Python snippet."""

from __future__ import annotations

from collections.abc import Mapping
from pprint import pformat

from .protocol import normalize_intent


def generate_intent_python(
    intent: Mapping[str, object],
    *,
    config_path: str = "config/nier.yaml",
) -> str:
    """Return runnable Python that reconnects to Nier and starts the Intent.

    Extras or fields that cannot be reconstructed through Android's ``am``
    command are omitted from the snippet and called out with TODO comments.
    """
    if not isinstance(intent, Mapping):
        raise ValueError("intent must be a mapping")
    if not isinstance(config_path, str) or not config_path:
        raise ValueError("config_path must be a non-empty string")

    payload = dict(intent)
    component = payload.get("component")
    root_launch = isinstance(component, Mapping) and component.get("exported") is False
    notes: list[str] = []
    if root_launch:
        notes.append(
            "The Activity is not exported; root=True requires a rooted device with working su."
        )
    if payload.get("action_truncated"):
        payload["action"] = None
        payload["action_truncated"] = False
        notes.append("The captured action was truncated and has been omitted.")
    if payload.get("data_truncated"):
        payload["data"] = None
        payload["data_truncated"] = False
        notes.append("The captured data URI was truncated and has been omitted.")
    if payload.get("type_truncated"):
        payload["type"] = None
        payload["type_truncated"] = False
        notes.append("The captured MIME type was truncated and has been omitted.")
    if payload.get("package_truncated"):
        payload["package"] = None
        payload["package_truncated"] = False
        notes.append("The captured package was truncated and has been omitted.")
    if payload.get("categories_truncated"):
        payload["categories"] = []
        payload["categories_truncated"] = False
        notes.append("Some Intent categories were omitted by the capture limit.")

    if payload.get("extras_truncated"):
        notes.append("Some extras were omitted by the capture limit.")
        payload["extras_truncated"] = False
    if payload.get("extras_unavailable"):
        notes.append("The captured Bundle was still parcelled; its extras were not read.")
        payload["extras_unavailable"] = False

    raw_extras = payload.get("extras", {})
    if not isinstance(raw_extras, Mapping):
        raise ValueError("intent extras must be a mapping")
    extras: dict[str, object] = {}
    for key, extra in raw_extras.items():
        try:
            candidate = dict(payload)
            candidate["extras"] = {key: extra}
            normalized = normalize_intent(candidate)
        except (TypeError, ValueError) as exc:
            kind = extra.get("type", "unknown") if isinstance(extra, Mapping) else "unknown"
            notes.append(f"Extra {key!r} ({kind}) was omitted: {exc}.")
            continue
        normalized_extras = normalized["extras"]
        assert isinstance(normalized_extras, Mapping)
        extras[str(key)] = normalized_extras[str(key)]
    payload["extras"] = extras

    normalized_payload = normalize_intent(payload)
    code_lines = ["from nier import connect", ""]
    code_lines.extend(f"# TODO: {note}" for note in notes)
    if notes:
        code_lines.append("")
    code_lines.extend(
        [
            f"intent = {pformat(normalized_payload, width=88, sort_dicts=False)}",
            "",
            f"with connect({config_path!r}) as phone:",
            "    result = phone.start_intent(intent, root=True)"
            if root_launch
            else "    result = phone.start_intent(intent)",
            "    print('Activity launch:', 'succeeded' if result.success else 'failed')",
        ]
    )
    return "\n".join(code_lines) + "\n"
