"""Configuration loading with explicit defaults and environment-backed secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError


@dataclass(frozen=True)
class DeviceConfig:
    serial: str | None = None
    adb_path: str = "adb"
    remote_host: str | None = None
    remote_port: int = 5555
    auto_connect: bool = True
    adb_server_host: str | None = None
    adb_server_port: int = 5037
    uinput_binary: str = "/data/local/tmp/nier-uinput"
    uinput_device: str = "/dev/uinput"
    use_uinput: bool = True
    connect_timeout_seconds: float = 10.0


@dataclass(frozen=True)
class RuntimeConfig:
    action_timeout_seconds: float = 15.0
    retries: int = 2
    output_dir: Path = Path("artifacts")


@dataclass(frozen=True)
class LoggingConfig:
    """Host logging verbosity: 0, 1 (v), 2 (vv), or 3 (vvv)."""

    verbosity: int = 0

    @property
    def level(self) -> str:
        """Return the compact CLI-style name for this verbosity."""
        return "quiet" if self.verbosity == 0 else "v" * self.verbosity


@dataclass(frozen=True)
class OcrConfig:
    provider: str = "paddleocr"
    lang: str = "ch"
    base_url: str | None = None
    api_key_env: str = "PADDLEOCR_ACCESS_TOKEN"
    model: str = "PP-OCRv6"
    request_timeout_seconds: float = 300.0
    poll_timeout_seconds: float = 600.0
    api_key_value: str | None = field(default=None, repr=False)

    @property
    def api_key(self) -> str | None:
        return self.api_key_value or os.getenv(self.api_key_env)


@dataclass(frozen=True)
class LlmConfig:
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 60.0
    api_key_value: str | None = field(default=None, repr=False)

    @property
    def api_key(self) -> str | None:
        return self.api_key_value or os.getenv(self.api_key_env)


@dataclass(frozen=True)
class SysOneConfig:
    """Configuration for Nier's SysOne typed-decision integration."""

    provider: str = "typesafe"
    base_url: str = "https://api.typesafe.ai/v1/systemone"
    api_key_env: str = "SYS_ONE_API_KEY"
    # The upstream service still requires this model ID on the wire.
    model: str = "jev-latest"
    timeout_seconds: float = 30.0
    confidence_threshold: float = 0.75
    api_key_value: str | None = field(default=None, repr=False)

    @property
    def api_key(self) -> str | None:
        return (
            self.api_key_value
            or os.getenv(self.api_key_env)
            or os.getenv("TYPESAFE_API_KEY")
        )


class HookMode(str, Enum):
    AUTO = "auto"
    ROOT = "root"
    NON_ROOT = "non-root"


@dataclass(frozen=True)
class HookConfig:
    """Configuration for optional WebView instrumentation and Intent capture.

    force_system_back is a root-Frida opt-in. When enabled, the hook suppresses
    common application-owned Java back callbacks so a back action can reach
    the platform default behavior. Root WebView instrumentation uses the
    Frida server settings. The intent-hook CLI uses the target package, spawn
    mode, and timeout to listen for events from the installed LSPosed module.
    The Back policy is deliberately disabled by default because it changes
    application navigation semantics.
    """

    mode: HookMode = HookMode.AUTO
    target_package: str | None = None
    spawn: bool = False
    frida_server_path: str = "/data/local/tmp/frida-server"
    auto_start_frida_server: bool = False
    timeout_seconds: float = 10.0
    force_system_back: bool = False


class InputTextMode(str, Enum):
    SHELL = "shell"
    IME = "ime"


@dataclass(frozen=True)
class InputTextConfig:
    """Configuration for the optional Unicode-capable text input path."""

    mode: InputTextMode = InputTextMode.SHELL
    ime_component: str = "icu.rina.nier.backend/.NierInputMethodService"
    provider_authority: str = "icu.rina.nier.backend.input"
    auto_enable: bool = False
    restore_previous: bool = True
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class ModelConfig:
    ocr: OcrConfig = OcrConfig()
    llm: LlmConfig = LlmConfig()
    sysone: SysOneConfig = SysOneConfig()
    # Named providers allow different models for planning, monitoring, and
    # visual analysis while keeping the singular fields backward-compatible.
    ocr_providers: Mapping[str, OcrConfig] = field(default_factory=dict)
    llm_providers: Mapping[str, LlmConfig] = field(default_factory=dict)
    sysone_providers: Mapping[str, SysOneConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    device: DeviceConfig = DeviceConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    models: ModelConfig = ModelConfig()
    hook: HookConfig = HookConfig()
    input_text: InputTextConfig = InputTextConfig()
    logging: LoggingConfig = LoggingConfig()


def _section(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{name} must be a mapping")
    return value


def _positive(value: Any, name: str, *, allow_zero: bool = False) -> Any:
    number = float(value)
    if number < 0 or (number == 0 and not allow_zero):
        raise ConfigurationError(f"{name} must be positive")
    return value


def _boolean(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ConfigurationError(f"{name} must be a boolean")


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise ConfigurationError(f"{name} must not be empty")
    return text


def _verbosity(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{name} must be 0, 1, 2, 3, v, vv, or vvv")
    if isinstance(value, str):
        normalized = value.strip().lower()
        aliases = {"quiet": 0, "none": 0, "v": 1, "vv": 2, "vvv": 3}
        if normalized in aliases:
            return aliases[normalized]
        try:
            value = int(normalized)
        except ValueError as exc:
            raise ConfigurationError(
                f"{name} must be 0, 1, 2, 3, v, vv, or vvv"
            ) from exc
    if isinstance(value, int) and 0 <= value <= 3:
        return value
    raise ConfigurationError(f"{name} must be 0, 1, 2, 3, v, vv, or vvv")


def _port(value: Any, name: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError(f"{name} must be between 1 and 65535")
    return port


def _parse_sysone_config(data: Mapping[str, Any], prefix: str) -> SysOneConfig:
    provider = str(data.get("provider", "typesafe")).strip()
    base_url = str(data.get("base_url", "https://api.typesafe.ai/v1/systemone")).strip()
    api_key_env = str(data.get("api_key_env", "SYS_ONE_API_KEY")).strip()
    api_key_value = _optional_text(data.get("api_key"), f"{prefix}.api_key")
    model = str(data.get("model", "jev-latest")).strip()
    if not provider:
        raise ConfigurationError(f"{prefix}.provider must not be empty")
    if not base_url:
        raise ConfigurationError(f"{prefix}.base_url must not be empty")
    if not api_key_env:
        raise ConfigurationError(f"{prefix}.api_key_env must not be empty")
    if not model:
        raise ConfigurationError(f"{prefix}.model must not be empty")
    timeout_seconds = float(
        _positive(
            data.get("timeout_seconds", 30.0),
            f"{prefix}.timeout_seconds",
        )
    )
    confidence_threshold = float(data.get("confidence_threshold", 0.75))
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ConfigurationError(f"{prefix}.confidence_threshold must be between 0 and 1")
    return SysOneConfig(
        provider=provider,
        base_url=base_url,
        api_key_env=api_key_env,
        model=model,
        timeout_seconds=timeout_seconds,
        confidence_threshold=confidence_threshold,
        api_key_value=api_key_value,
    )


def _parse_ocr_config(data: Mapping[str, Any], prefix: str) -> OcrConfig:
    provider = str(data.get("provider", "paddleocr")).strip()
    lang = str(data.get("lang", "ch")).strip()
    base_url = _optional_text(data.get("base_url"), f"{prefix}.base_url")
    api_key_env = str(data.get("api_key_env", "PADDLEOCR_ACCESS_TOKEN")).strip()
    api_key_value = _optional_text(data.get("api_key"), f"{prefix}.api_key")
    model = str(data.get("model", "PP-OCRv6")).strip()
    if not provider:
        raise ConfigurationError(f"{prefix}.provider must not be empty")
    if not lang:
        raise ConfigurationError(f"{prefix}.lang must not be empty")
    if not api_key_env:
        raise ConfigurationError(f"{prefix}.api_key_env must not be empty")
    if not model:
        raise ConfigurationError(f"{prefix}.model must not be empty")
    request_timeout_seconds = float(
        _positive(
            data.get("request_timeout_seconds", 300.0),
            f"{prefix}.request_timeout_seconds",
        )
    )
    poll_timeout_seconds = float(
        _positive(
            data.get("poll_timeout_seconds", 600.0),
            f"{prefix}.poll_timeout_seconds",
        )
    )
    return OcrConfig(
        provider=provider,
        lang=lang,
        base_url=base_url,
        api_key_env=api_key_env,
        model=model,
        request_timeout_seconds=request_timeout_seconds,
        poll_timeout_seconds=poll_timeout_seconds,
        api_key_value=api_key_value,
    )


def from_mapping(data: Mapping[str, Any]) -> AppConfig:
    device = _section(data, "device")
    runtime = _section(data, "runtime")
    logging_config_data = _section(data, "logging")
    if not logging_config_data and "log" in data:
        logging_config_data = _section(data, "log")
    models = _section(data, "models")
    removed_model_keys = {"jev", "jev_providers"}.intersection(models)
    if removed_model_keys:
        removed = ", ".join(sorted(f"models.{key}" for key in removed_model_keys))
        raise ConfigurationError(
            f"removed model configuration {removed}; use models.sysone or "
            "models.sysone_providers"
        )
    hook = _section(data, "hook")
    input_text = _section(data, "input_text")
    ocr = _section(models, "ocr")
    llm = _section(models, "llm")
    sysone = _section(models, "sysone")

    ocr_config = _parse_ocr_config(ocr, "models.ocr")
    llm_config = LlmConfig(
        provider=str(llm.get("provider", "openai-compatible")),
        base_url=str(llm.get("base_url", "https://api.openai.com/v1")),
        api_key_env=str(llm.get("api_key_env", "OPENAI_API_KEY")),
        model=str(llm.get("model", "gpt-4o-mini")),
        timeout_seconds=float(_positive(llm.get("timeout_seconds", 60.0), "models.llm.timeout_seconds")),
        api_key_value=_optional_text(llm.get("api_key"), "models.llm.api_key"),
    )
    sysone_config = _parse_sysone_config(sysone, "models.sysone")
    logging_config = LoggingConfig(
        verbosity=_verbosity(
            logging_config_data.get(
                "verbosity",
                logging_config_data.get("level", 0),
            ),
            "logging.verbosity",
        )
    )

    def named_ocr() -> dict[str, OcrConfig]:
        values = _section(models, "ocr_providers")
        if not values:
            return {"default": ocr_config}
        return {
            str(name): _parse_ocr_config(
                _section(values, str(name)),
                f"models.ocr_providers.{name}",
            )
            for name in values
        }

    def named_llm() -> dict[str, LlmConfig]:
        values = _section(models, "llm_providers")
        if not values:
            return {"default": llm_config}
        providers: dict[str, LlmConfig] = {}
        for name in values:
            value = _section(values, str(name))
            providers[str(name)] = LlmConfig(
                provider=str(value.get("provider", "openai-compatible")),
                base_url=str(value.get("base_url", "https://api.openai.com/v1")),
                api_key_env=str(value.get("api_key_env", "OPENAI_API_KEY")),
                model=str(value.get("model", "gpt-4o-mini")),
                timeout_seconds=float(_positive(value.get("timeout_seconds", 60.0), f"models.llm_providers.{name}.timeout_seconds")),
                api_key_value=_optional_text(
                    value.get("api_key"),
                    f"models.llm_providers.{name}.api_key",
                ),
            )
        return providers

    def named_sysone() -> dict[str, SysOneConfig]:
        values = _section(models, "sysone_providers")
        if not values:
            # SysOne is optional. Do not make an unconfigured default provider
            # part of every router, but make an explicitly supplied singular
            # section available under the conventional default name.
            return {"default": sysone_config} if "sysone" in models else {}
        return {
            str(name): _parse_sysone_config(
                _section(values, str(name)),
                f"models.sysone_providers.{name}",
            )
            for name in values
        }

    retries = int(runtime.get("retries", 2))
    if retries < 0:
        raise ConfigurationError("runtime.retries must not be negative")

    serial = _optional_text(device.get("serial"), "device.serial")
    remote_host = _optional_text(device.get("remote_host"), "device.remote_host")
    if serial is not None and remote_host is not None:
        raise ConfigurationError("device.serial and device.remote_host are mutually exclusive")

    try:
        hook_mode = HookMode(str(hook.get("mode", HookMode.AUTO.value)).lower())
    except ValueError as exc:
        accepted = ", ".join(mode.value for mode in HookMode)
        raise ConfigurationError(f"hook.mode must be one of: {accepted}") from exc
    target_package_value = hook.get("target_package")
    target_package = None if target_package_value is None else str(target_package_value).strip()
    if target_package == "":
        raise ConfigurationError("hook.target_package must not be empty")
    frida_server_path = str(hook.get("frida_server_path", "/data/local/tmp/frida-server"))
    if not frida_server_path:
        raise ConfigurationError("hook.frida_server_path must not be empty")
    force_system_back = _boolean(
        hook.get("force_system_back", False),
        "hook.force_system_back",
    )
    if force_system_back and target_package is None:
        raise ConfigurationError(
            "hook.target_package is required when hook.force_system_back is enabled"
        )
    if force_system_back and hook_mode is HookMode.NON_ROOT:
        raise ConfigurationError("hook.force_system_back requires root or auto hook mode")

    try:
        input_text_mode = InputTextMode(str(input_text.get("mode", InputTextMode.SHELL.value)).lower())
    except ValueError as exc:
        accepted = ", ".join(mode.value for mode in InputTextMode)
        raise ConfigurationError(f"input_text.mode must be one of: {accepted}") from exc
    ime_component = str(
        input_text.get("ime_component", "icu.rina.nier.backend/.NierInputMethodService")
    ).strip()
    if not ime_component:
        raise ConfigurationError("input_text.ime_component must not be empty")
    provider_authority = str(
        input_text.get("provider_authority", "icu.rina.nier.backend.input")
    ).strip()
    if not provider_authority:
        raise ConfigurationError("input_text.provider_authority must not be empty")

    return AppConfig(
        device=DeviceConfig(
            serial=serial,
            adb_path=str(device.get("adb_path", "adb")),
            remote_host=remote_host,
            remote_port=_port(device.get("remote_port", 5555), "device.remote_port"),
            auto_connect=_boolean(device.get("auto_connect", True), "device.auto_connect"),
            adb_server_host=_optional_text(device.get("adb_server_host"), "device.adb_server_host"),
            adb_server_port=_port(device.get("adb_server_port", 5037), "device.adb_server_port"),
            uinput_binary=str(device.get("uinput_binary", "/data/local/tmp/nier-uinput")),
            uinput_device=str(device.get("uinput_device", "/dev/uinput")),
            use_uinput=_boolean(device.get("use_uinput", True), "device.use_uinput"),
            connect_timeout_seconds=float(_positive(device.get("connect_timeout_seconds", 10.0), "device.connect_timeout_seconds")),
        ),
        runtime=RuntimeConfig(
            action_timeout_seconds=float(_positive(runtime.get("action_timeout_seconds", 15.0), "runtime.action_timeout_seconds")),
            retries=retries,
            output_dir=Path(runtime.get("output_dir", "artifacts")),
        ),
        models=ModelConfig(
            ocr=ocr_config,
            llm=llm_config,
            sysone=sysone_config,
            ocr_providers=named_ocr(),
            llm_providers=named_llm(),
            sysone_providers=named_sysone(),
        ),
        hook=HookConfig(
            mode=hook_mode,
            target_package=target_package,
            spawn=_boolean(hook.get("spawn", False), "hook.spawn"),
            frida_server_path=frida_server_path,
            auto_start_frida_server=_boolean(
                hook.get("auto_start_frida_server", False),
                "hook.auto_start_frida_server",
            ),
            timeout_seconds=float(_positive(hook.get("timeout_seconds", 10.0), "hook.timeout_seconds")),
            force_system_back=force_system_back,
        ),
        input_text=InputTextConfig(
            mode=input_text_mode,
            ime_component=ime_component,
            provider_authority=provider_authority,
            auto_enable=_boolean(input_text.get("auto_enable", False), "input_text.auto_enable"),
            restore_previous=_boolean(
                input_text.get("restore_previous", True),
                "input_text.restore_previous",
            ),
            timeout_seconds=float(
                _positive(input_text.get("timeout_seconds", 5.0), "input_text.timeout_seconds")
            ),
        ),
        logging=logging_config,
    )


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
    except OSError as exc:
        raise ConfigurationError(f"cannot read config {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigurationError("top-level config must be a mapping")
    return from_mapping(data)
