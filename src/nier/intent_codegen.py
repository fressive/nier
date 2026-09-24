"""Render captured Android Intent fields as reusable Kotlin or Java code."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
import re


_INTEGER = re.compile(r"-?\d+\Z")


def _string(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _number(value: object, *, integer: bool = False) -> str:
    if integer:
        raw = str(value)
        if not _INTEGER.fullmatch(raw):
            raise ValueError(f"invalid integer Intent extra: {value!r}")
        return raw
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite Intent extra: {value!r}")
    rendered = repr(number)
    if rendered.endswith(".0"):
        rendered = rendered[:-2]
    return rendered


def _char(value: object, language: str) -> str:
    text = str(value)
    if len(text) != 1:
        raise ValueError(f"invalid char Intent extra: {value!r}")
    escaped = text.replace("\\", "\\\\").replace("'", "\\'")
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f"'{escaped}'"


def _extra_expression(extra: object, language: str) -> str | None:
    if not isinstance(extra, Mapping):
        return None
    kind = extra.get("type")
    value = extra.get("value")

    if kind == "string":
        return _string(value)
    if kind == "boolean" and isinstance(value, bool):
        return "true" if value else "false"
    if kind in {"byte", "short", "int", "long"}:
        literal = _number(value, integer=True)
        if kind == "long":
            return f"{literal}L"
        if language == "kotlin" and kind in {"byte", "short"}:
            cast = "Byte" if kind == "byte" else "Short"
            return f"{literal}.to{cast}()"
        if language == "java" and kind in {"byte", "short"}:
            cast = "byte" if kind == "byte" else "short"
            return f"({cast}) {literal}"
        return literal
    if kind in {"float", "double"}:
        literal = _number(value)
        if kind == "float":
            return f"{literal}f"
        return literal if any(char in literal for char in ".eE") else f"{literal}.0"
    if kind == "char":
        return _char(value, language)
    if kind == "uri":
        return f"Uri.parse({_string(value)})"
    if kind == "component" and isinstance(value, Mapping):
        package = value.get("package")
        class_name = value.get("class")
        if package is None or class_name is None:
            return None
        return f"ComponentName({_string(package)}, {_string(class_name)})"

    array_types = {
        "string_array": "string",
        "boolean_array": "boolean",
        "byte_array": "byte",
        "short_array": "short",
        "char_array": "char",
        "int_array": "int",
        "long_array": "long",
        "float_array": "float",
        "double_array": "double",
    }
    if kind in array_types and isinstance(value, Sequence) and not isinstance(value, str):
        element_type = array_types[kind]
        rendered_items: list[str] = []
        for item in value:
            rendered = _extra_expression({"type": element_type, "value": item}, language)
            if rendered is None:
                return None
            if element_type in {"byte", "short"} and language == "kotlin":
                rendered = _number(item, integer=True)
            rendered_items.append(rendered)
        if language == "kotlin":
            factory = "arrayOf" if element_type == "string" else f"{element_type}ArrayOf"
            return f"{factory}({', '.join(rendered_items)})"
        java_types = {
            "string": "String",
            "boolean": "boolean",
            "byte": "byte",
            "short": "short",
            "char": "char",
            "int": "int",
            "long": "long",
            "float": "float",
            "double": "double",
        }
        return f"new {java_types[element_type]}[] {{{', '.join(rendered_items)}}}"
    return None


def _render_fields(intent: Mapping[str, object], language: str) -> list[str]:
    lines: list[str] = []
    component = intent.get("component")
    if isinstance(component, Mapping):
        package = component.get("package")
        class_name = component.get("class")
        if package and class_name:
            lines.append(
                f"intent.setComponent(ComponentName({_string(package)}, {_string(class_name)}))"
            )

    action = intent.get("action")
    if action:
        lines.append(f"intent.setAction({_string(action)})")

    package_name = intent.get("package")
    if package_name:
        lines.append(f"intent.setPackage({_string(package_name)})")

    data = intent.get("data")
    mime_type = intent.get("type")
    if data and mime_type:
        lines.append(f"intent.setDataAndType(Uri.parse({_string(data)}), {_string(mime_type)})")
    elif data:
        lines.append(f"intent.setData(Uri.parse({_string(data)}))")
    elif mime_type:
        lines.append(f"intent.setType({_string(mime_type)})")

    categories = intent.get("categories")
    if isinstance(categories, Sequence) and not isinstance(categories, str):
        for category in categories:
            lines.append(f"intent.addCategory({_string(category)})")

    flags = intent.get("flags")
    if isinstance(flags, int):
        lines.append(f"intent.setFlags({flags})")

    extras = intent.get("extras")
    unsupported: list[tuple[str, object]] = []
    if isinstance(extras, Mapping):
        for key, extra in extras.items():
            expression = _extra_expression(extra, language)
            if expression is None:
                extra_type = extra.get("value", "unknown") if isinstance(extra, Mapping) else "unknown"
                unsupported.append((str(key), extra_type))
                continue
            lines.append(f"intent.putExtra({_string(key)}, {expression})")

    for key, extra_type in unsupported:
        lines.append(f"// TODO: extra {_string(key)} ({extra_type}) was not reconstructed.")
    if intent.get("extras_truncated"):
        lines.append("// TODO: some extras were omitted because the capture limit was reached.")
    return lines


def generate_intent_code(intent: Mapping[str, object], language: str = "kotlin") -> str:
    """Return reusable Activity code that launches a captured Intent.

    Supported scalar and primitive-array extras are restored with their
    original Java types. Parcelable and custom Serializable extras are shown
    as TODO comments because their class-specific reconstruction is unsafe.
    """
    selected = language.strip().lower()
    if selected not in {"kotlin", "java"}:
        raise ValueError("language must be 'kotlin' or 'java'")
    if not isinstance(intent, Mapping):
        raise ValueError("intent must be a mapping")

    lines = _render_fields(intent, selected)
    if selected == "kotlin":
        body = "\n".join(f"        {line}" for line in lines)
        if body:
            body = "\n" + body + "\n    "
        return (
            "import android.app.Activity\n"
            "import android.content.ComponentName\n"
            "import android.content.Intent\n"
            "import android.net.Uri\n\n"
            "fun launchCapturedIntent(activity: Activity) {\n"
            f"    val intent = Intent(){body}\n"
            "    activity.startActivity(intent)\n"
            "}\n"
        )

    body = "\n".join(f"        {line};" if not line.startswith("//") else f"        {line}" for line in lines)
    if body:
        body = "\n" + body + "\n"
    return (
        "import android.app.Activity;\n"
        "import android.content.ComponentName;\n"
        "import android.content.Intent;\n"
        "import android.net.Uri;\n\n"
        "public final class CapturedIntentLauncher {\n"
        "    private CapturedIntentLauncher() {}\n\n"
        "    public static void launch(Activity activity) {\n"
        f"        Intent intent = new Intent();{body}"
        "        activity.startActivity(intent);\n"
        "    }\n"
        "}\n"
    )
