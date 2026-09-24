"""Build configured model providers without coupling the runtime to SDKs."""

from __future__ import annotations

from ..config import AppConfig
from .decision import TextMatchDecisionProvider
from .sysone import SysOneDecisionProvider, SysOneProvider
from .llm import OpenAICompatibleProvider
from .ocr import PaddleOcrApiProvider, PaddleOcrCompatibleApiProvider, PaddleOcrProvider
from .router import ModelRouter


def create_model_router(config: AppConfig) -> ModelRouter:
    ocr_providers = {
        name: _create_ocr(
            spec.provider,
            spec.lang,
            spec.api_key,
            spec.api_key_env,
            spec.base_url,
            spec.model,
            spec.request_timeout_seconds,
            spec.poll_timeout_seconds,
        )
        for name, spec in config.models.ocr_providers.items()
    }
    llm_providers = {
        name: _create_llm(spec.provider, spec.base_url, spec.api_key, spec.model, spec.timeout_seconds)
        for name, spec in config.models.llm_providers.items()
    }
    sysone_providers = {
        name: _create_sysone(
            spec.provider,
            spec.base_url,
            spec.api_key,
            spec.api_key_env,
            spec.model,
            spec.timeout_seconds,
        )
        for name, spec in config.models.sysone_providers.items()
    }
    decision_providers = {"text-match": TextMatchDecisionProvider()}
    for name, client in sysone_providers.items():
        decision_providers[f"sysone:{name}"] = SysOneDecisionProvider(
            client,
            confidence_threshold=config.models.sysone_providers[name].confidence_threshold,
        )
    if "default" in sysone_providers:
        decision_providers["sysone"] = decision_providers["sysone:default"]
    return ModelRouter(
        ocr_providers=ocr_providers,
        decision_providers=decision_providers,
        llm_providers=llm_providers,
        sysone_providers=sysone_providers,
    )


def _create_ocr(
    provider: str,
    lang: str,
    api_key: str | None = None,
    api_key_env: str = "PADDLEOCR_ACCESS_TOKEN",
    base_url: str | None = None,
    model: str = "PP-OCRv6",
    request_timeout: float = 300.0,
    poll_timeout: float = 600.0,
):
    if provider == "paddleocr":
        return PaddleOcrProvider(lang=lang)
    if provider in {"paddleocr-api", "paddleocr-online"}:
        return PaddleOcrApiProvider(
            lang=lang,
            api_key=api_key,
            api_key_env=api_key_env,
            base_url=base_url,
            model=model,
            request_timeout=request_timeout,
            poll_timeout=poll_timeout,
        )
    if provider in {"paddleocr-compatible", "paddleocr-local-api"}:
        if not base_url:
            raise ValueError("paddleocr-compatible requires models.ocr.base_url")
        return PaddleOcrCompatibleApiProvider(
            base_url=base_url,
            request_timeout=request_timeout,
        )
    raise ValueError(f"unsupported OCR provider: {provider}")


def _create_llm(provider: str, base_url: str, api_key: str | None, model: str, timeout: float):
    if provider != "openai-compatible":
        raise ValueError(f"unsupported LLM provider: {provider}")
    return OpenAICompatibleProvider(base_url=base_url, api_key=api_key, model=model, timeout=timeout)


def _create_sysone(
    provider: str,
    base_url: str,
    api_key: str | None,
    api_key_env: str,
    model: str,
    timeout: float,
):
    if provider != "typesafe":
        raise ValueError(f"unsupported SysOne provider: {provider}")
    return SysOneProvider(
        base_url=base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        model=model,
        timeout=timeout,
    )
