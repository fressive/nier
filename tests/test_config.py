from __future__ import annotations

from pathlib import Path

import pytest

from nier.config import HookMode, InputTextMode, from_mapping, load_config
from nier.errors import ConfigurationError


def test_load_example_shape(tmp_path: Path) -> None:
    path = tmp_path / "nier.yaml"
    path.write_text(
        """
device:
  serial: emulator-5554
runtime:
  retries: 3
models:
  llm:
    api_key_env: TEST_NIER_KEY
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.device.serial == "emulator-5554"
    assert config.runtime.retries == 3
    assert config.models.llm.api_key_env == "TEST_NIER_KEY"


def test_logging_verbosity_accepts_numeric_and_v_aliases() -> None:
    assert from_mapping({}).logging.verbosity == 0
    assert from_mapping({"logging": {"verbosity": 2}}).logging.verbosity == 2
    assert from_mapping({"logging": {"verbosity": "vvv"}}).logging.verbosity == 3
    assert from_mapping({"logging": {"level": "v"}}).logging.verbosity == 1
    assert from_mapping({"log": {"level": "vv"}}).logging.level == "vv"


def test_invalid_logging_verbosity_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match=r"logging\.verbosity"):
        from_mapping({"logging": {"verbosity": 4}})


def test_negative_retry_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        from_mapping({"runtime": {"retries": -1}})


def test_invalid_section_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        from_mapping({"device": "not-a-map"})


def test_named_model_providers_are_preserved() -> None:
    config = from_mapping(
        {
            "models": {
                "llm_providers": {
                    "planner": {"model": "planner-model"},
                    "monitor": {"model": "monitor-model"},
                }
            }
        }
    )
    assert config.models.llm_providers["planner"].model == "planner-model"
    assert config.models.llm_providers["monitor"].model == "monitor-model"


def test_sysone_uses_typesafe_provider_configuration() -> None:
    config = from_mapping(
        {
            "models": {
                "sysone": {
                    "provider": "typesafe",
                    "model": "jev-latest",
                },
                "sysone_providers": {
                    "primary": {
                        "provider": "typesafe",
                        "model": "jev-latest",
                    }
                },
            }
        }
    )

    assert config.models.sysone.provider == "typesafe"
    assert config.models.sysone.model == "jev-latest"
    assert config.models.sysone_providers["primary"].provider == "typesafe"


@pytest.mark.parametrize("old_name", ("jev", "jev_providers"))
def test_removed_sysone_configuration_names_are_rejected(old_name: str) -> None:
    with pytest.raises(ConfigurationError, match="removed model configuration"):
        from_mapping({"models": {old_name: {}}})


def test_remote_ocr_provider_settings_are_preserved() -> None:
    config = from_mapping(
        {
            "models": {
                "ocr_providers": {
                    "cloud": {
                        "provider": "paddleocr-api",
                        "api_key": "ocr-secret",
                        "api_key_env": "OCR_TOKEN",
                        "base_url": "https://ocr.example.test",
                        "model": "PP-OCRv5",
                        "request_timeout_seconds": 20,
                        "poll_timeout_seconds": 80,
                    }
                }
            }
        }
    )

    ocr = config.models.ocr_providers["cloud"]
    assert ocr.provider == "paddleocr-api"
    assert ocr.api_key == "ocr-secret"
    assert ocr.api_key_env == "OCR_TOKEN"
    assert ocr.base_url == "https://ocr.example.test"
    assert ocr.model == "PP-OCRv5"
    assert ocr.request_timeout_seconds == 20
    assert ocr.poll_timeout_seconds == 80


def test_model_api_key_can_be_loaded_directly_or_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_TOKEN", "env-llm-secret")
    config = from_mapping(
        {
            "models": {
                "llm": {
                    "api_key_env": "LLM_TOKEN",
                },
                "sysone": {
                    "api_key": "direct-sysone-secret",
                },
            }
        }
    )

    assert config.models.llm.api_key == "env-llm-secret"
    assert config.models.sysone.api_key == "direct-sysone-secret"


def test_hook_modes_are_parsed_and_validated() -> None:
    assert from_mapping({}).hook.auto_start_frida_server is True

    config = from_mapping(
        {
            "hook": {
                "mode": "root",
                "target_package": "com.example.app",
                "spawn": True,
                "auto_start_frida_server": True,
                "force_system_back": True,
            }
        }
    )
    assert config.hook.mode is HookMode.ROOT
    assert config.hook.target_package == "com.example.app"
    assert config.hook.spawn is True
    assert config.hook.auto_start_frida_server is True
    assert config.hook.force_system_back is True

    lsposed_config = from_mapping(
        {"hook": {"mode": "lsposed", "target_package": "com.example.app"}}
    )
    assert lsposed_config.hook.mode is HookMode.LSPOSED


def test_invalid_hook_mode_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        from_mapping({"hook": {"mode": "magic"}})


def test_force_system_back_requires_a_root_capable_target() -> None:
    with pytest.raises(ConfigurationError, match="target_package"):
        from_mapping({"hook": {"force_system_back": True}})
    with pytest.raises(ConfigurationError, match="root Frida or auto"):
        from_mapping(
            {
                "hook": {
                    "mode": "non-root",
                    "target_package": "com.example.app",
                    "force_system_back": True,
                }
            }
        )
    with pytest.raises(ConfigurationError, match="root Frida or auto"):
        from_mapping(
            {
                "hook": {
                    "mode": "lsposed",
                    "target_package": "com.example.app",
                    "force_system_back": True,
                }
            }
        )


def test_force_system_back_must_be_boolean() -> None:
    with pytest.raises(ConfigurationError, match="force_system_back"):
        from_mapping(
            {
                "hook": {
                    "target_package": "com.example.app",
                    "force_system_back": "sometimes",
                }
            }
        )


def test_ime_text_backend_configuration_is_parsed() -> None:
    config = from_mapping(
        {
            "input_text": {
                "mode": "ime",
                "ime_component": "icu.rina.nier.backend/.NierInputMethodService",
                "auto_enable": True,
                "restore_previous": False,
                "timeout_seconds": 7,
            }
        }
    )

    assert config.input_text.mode is InputTextMode.IME
    assert config.input_text.auto_enable is True
    assert config.input_text.restore_previous is False
    assert config.input_text.timeout_seconds == 7


def test_invalid_text_backend_mode_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        from_mapping({"input_text": {"mode": "keyboard"}})


def test_remote_adb_settings_are_parsed() -> None:
    config = from_mapping(
        {
            "device": {
                "remote_host": "192.0.2.10",
                "remote_port": 5555,
                "auto_connect": False,
                "adb_server_host": "192.0.2.20",
                "adb_server_port": 5038,
            }
        }
    )

    assert config.device.remote_host == "192.0.2.10"
    assert config.device.remote_port == 5555
    assert config.device.auto_connect is False
    assert config.device.adb_server_host == "192.0.2.20"
    assert config.device.adb_server_port == 5038


def test_remote_adb_rejects_ambiguous_target() -> None:
    with pytest.raises(ConfigurationError):
        from_mapping(
            {
                "device": {
                    "serial": "usb-device",
                    "remote_host": "192.0.2.10",
                }
            }
        )


def test_remote_adb_rejects_invalid_port() -> None:
    with pytest.raises(ConfigurationError):
        from_mapping({"device": {"remote_port": 70000}})
