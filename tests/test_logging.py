from __future__ import annotations

from nier.cli import _parser
from nier.logging_utils import configure_logging, request, response, step, tool_call


def test_cli_accepts_compact_verbosity_flags() -> None:
    assert _parser().parse_args(["-v", "health"]).verbose == 1
    assert _parser().parse_args(["-vv", "health"]).verbose == 2
    assert _parser().parse_args(["-vvv", "health"]).verbose == 3


def test_logging_levels_add_steps_requests_and_responses(capsys) -> None:
    try:
        configure_logging(1)
        step("tap", x=10)
        tool_call("text", {"text": "do not copy this into logs"}, call_id="call_1")
        request("http", "POST", "https://example.test/api", body={"value": 1})
        response("http", 200, body={"value": 2})

        configure_logging(3)
        request(
            "http",
            "POST",
            "https://example.test/api?token=secret",
            headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
            body={"api_key": "secret", "file": "data:image/png;base64,AAAA"},
        )
        response("http", 200, body={"answer": "ok"})
        output = capsys.readouterr().err
        assert "[nier vvv] HTTP REQUEST" in output
        assert "[nier vvv] HTTP RESPONSE" in output
        assert output.count("HTTP REQUEST") == 1
        assert output.count("HTTP RESPONSE") == 1
        assert "[nier v] STEP tap" in output
        assert "[nier v] TOOL CALL model requested" in output
        assert "do not copy this into logs" not in output
        assert "<26 chars>" in output
        assert "secret" not in output
        assert "<data-uri" in output
        assert "<redacted>" in output
    finally:
        configure_logging(0)
