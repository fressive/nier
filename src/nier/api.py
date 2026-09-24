"""Small, script-friendly public API built on top of :mod:`nier.session`."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from difflib import SequenceMatcher
from math import ceil, floor, isfinite
from numbers import Real
from pathlib import Path
from re import Pattern
from typing import TYPE_CHECKING, Any, TypeAlias
from unicodedata import normalize

from .backends.adb import AdbBackend
from .config import AppConfig, load_config
from .errors import ConfigurationError, ModelError, UiElementNotFound
from .logging_utils import configure_logging, step
from .models.base import select_provider_name
from .models.sysone import SysOneAnswer, SysOneOptions, SysOneProvider
from .protocol import (
    ActionResult,
    ActivityInfo,
    Capabilities,
    Click,
    ImageFormat,
    InputText,
    Key,
    KeyCode,
    Point,
    Screenshot,
    Swipe,
    UiDump,
    validate_package_name,
)
from .results import RunRecorder
from .session import DeviceSession
from .ui import UiDocument, UiNode, _format_tree
from .ui import parse_uidump as parse_ui_dump
from .vision import ImageMatch, locate_template
from .widgets import WidgetList

if TYPE_CHECKING:
    from .agent import Agent, AgentRun
    from .models.base import LlmProvider, OcrProvider, TextSpan
    from .models.router import ModelRouter
    from .sysone_goal import SysOneGoal

PointLike: TypeAlias = Point | tuple[float, float]
Endpoint: TypeAlias = str | tuple[str, int]


class _LazyOcrProvider:
    """Create a configured OCR provider only when OCR is requested."""

    def __init__(self, create: Callable[[], OcrProvider]) -> None:
        self._create = create
        self._provider: OcrProvider | None = None

    def recognize(self, image: bytes) -> Sequence[TextSpan]:
        if self._provider is None:
            self._provider = self._create()
        return self._provider.recognize(image)


class _LazyLlmProvider:
    """Create the optional LLM only when bounded recovery is requested."""

    def __init__(self, create: Callable[[], LlmProvider]) -> None:
        self._create = create
        self._provider: LlmProvider | None = None

    def complete(self, prompt: str, *, image: bytes | None = None) -> str:
        if self._provider is None:
            self._provider = self._create()
        return self._provider.complete(prompt, image=image)

    def complete_with_tools(self, prompt: str, *, tools, image: bytes | None = None):
        if self._provider is None:
            self._provider = self._create()
        complete_with_tools = getattr(self._provider, "complete_with_tools", None)
        if not callable(complete_with_tools):
            raise ModelError(
                "LLM recovery actions require a provider with complete_with_tools()"
            )
        return complete_with_tools(prompt, tools=tools, image=image)


def _point(value: PointLike, *, normalized: bool) -> Point:
    if isinstance(value, Point):
        return value
    try:
        x, y = value
    except (TypeError, ValueError) as exc:
        raise ValueError("a point must be Point or an (x, y) pair") from exc
    return Point(float(x), float(y), normalized=normalized)


def _points(
    values: tuple[PointLike | float, ...], *, normalized: bool
) -> tuple[Point, ...]:
    if values and all(isinstance(value, (int, float)) for value in values):
        if len(values) < 4 or len(values) % 2:
            raise ValueError("numeric swipe coordinates must be x1, y1, x2, y2, ...")
        numbers = tuple(float(value) for value in values)
        return tuple(
            Point(numbers[index], numbers[index + 1], normalized=normalized)
            for index in range(0, len(numbers), 2)
        )
    point_values: list[PointLike] = []
    for value in values:
        if isinstance(value, (int, float)):
            raise TypeError("do not mix numeric coordinates with (x, y) pairs")
        point_values.append(value)
    return tuple(_point(value, normalized=normalized) for value in point_values)


def _image_format(value: ImageFormat | str) -> ImageFormat:
    if isinstance(value, ImageFormat):
        return value
    text = value.strip().upper()
    if text == "JPG":
        text = "JPEG"
    try:
        return ImageFormat(text)
    except ValueError as exc:
        raise ValueError("format must be 'png', 'jpg', or 'jpeg'") from exc


def _normalize_locator_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("text must be a string")
    normalized = " ".join(normalize("NFKC", value).casefold().split())
    if not normalized:
        raise ValueError("text must not be empty")
    return normalized


def _validate_text_score(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise ValueError("min_score must be a finite number between 0 and 1")


def _key_code(value: KeyCode | str) -> KeyCode:
    if isinstance(value, KeyCode):
        return value
    try:
        return KeyCode(value.strip().upper())
    except ValueError as exc:
        choices = ", ".join(code.value.lower() for code in KeyCode)
        raise ValueError(f"unknown key {value!r}; choose one of: {choices}") from exc


def _endpoint(value: Endpoint, default_port: int) -> tuple[str, int]:
    if isinstance(value, tuple):
        host, port = value
    else:
        text = value.strip()
        if text.startswith("["):
            closing = text.find("]")
            if closing < 0:
                raise ValueError(f"invalid endpoint: {value!r}")
            host = text[1:closing]
            remainder = text[closing + 1 :]
            if remainder and not remainder.startswith(":"):
                raise ValueError(f"invalid endpoint: {value!r}")
            port = default_port if not remainder else remainder[1:]
        elif text.count(":") == 1:
            host, port = text.rsplit(":", 1)
        else:
            host, port = text, default_port
    host = str(host).strip()
    if not host:
        raise ValueError("endpoint host must not be empty")
    try:
        port_number = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid endpoint port: {port!r}") from exc
    if not 1 <= port_number <= 65535:
        raise ValueError("endpoint port must be between 1 and 65535")
    return host, port_number


class Device:
    """A concise facade for common Android automation scripts."""

    def __init__(
        self,
        session: DeviceSession,
        *,
        output_dir: str | Path = "artifacts",
        app_config: AppConfig | None = None,
    ) -> None:
        self.session = session
        self.output_dir = Path(output_dir)
        self.app_config = app_config
        self._ocr_cache: dict[str, OcrProvider] = {}
        self._sysone_cache: dict[str, SysOneProvider] = {}
        if app_config is not None:
            configure_logging(app_config.logging.verbosity)

    def __enter__(self) -> Device:  # noqa: PYI034 -- typing.Self requires Python 3.11
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def health(self) -> bool:
        return self.session.health()

    def capabilities(self) -> Capabilities:
        return self.session.capabilities()

    def current_activity(self) -> ActivityInfo | None:
        """Return the foreground Android Activity when the backend reports it."""
        return self.session.current_activity()

    def list_apps(self) -> list[str]:
        """Return installed Android package names."""
        return self.session.list_apps()

    def list_app(self) -> list[str]:
        """Compatibility alias for :meth:`list_apps`."""
        return self.list_apps()

    def list_app_activities(self, package: str) -> list[str]:
        """Return fully qualified Activity class names for ``package``."""
        return self.session.list_app_activities(validate_package_name(package))

    def list_app_activity(self, package: str) -> list[str]:
        """Compatibility alias for :meth:`list_app_activities`."""
        return self.list_app_activities(package)

    def open_app(self, package: str) -> ActionResult:
        """Open an app through its launcher Activity."""
        return self.session.open_app(package)

    def launch_app(self, package: str) -> ActionResult:
        """Compatibility alias for :meth:`open_app`."""
        return self.open_app(package)

    def start_activity(self, package: str, activity: str) -> ActionResult:
        """Start an Activity by class name or ``package/class`` component."""
        return self.session.start_activity(package, activity)

    def open_activity(self, package: str, activity: str) -> ActionResult:
        """Compatibility alias for :meth:`start_activity`."""
        return self.start_activity(package, activity)

    def click(
        self,
        x: float,
        y: float,
        *,
        normalized: bool = False,
        duration_ms: int = 80,
    ) -> ActionResult:
        return self.session.execute(Click(Point(x, y, normalized), duration_ms))

    tap = click

    def tap_label(self, label: str | Pattern[str]) -> ActionResult:
        """Find a UI text/accessibility label and tap the center of its bounds.

        String labels match exactly. Pass a compiled ``re.Pattern`` to match
        using its ``search`` semantics. This captures a fresh UIAutomator dump
        and performs one tap. ``UiElementNotFound`` is raised when no matching
        text or content-description node with screen bounds is available.
        """
        def matches_value(value: str) -> bool:
            if not value:
                return False
            if isinstance(label, str):
                return value == label
            return label.search(value) is not None

        document = self.parse_uidump(prefer_webview=False)
        matching_nodes = tuple(
            node
            for node in document.walk()
            if matches_value(node.text) or matches_value(node.content_desc)
        )
        node = next(
            (match for match in matching_nodes if match.center is not None), None
        )
        if not matching_nodes:
            raise UiElementNotFound(f"no UI label matches {label!r}")
        if node is None:
            raise UiElementNotFound(
                f"UI label {label!r} matched no node with screen bounds"
            )
        center = node.center
        assert center is not None
        return self.tap(*center)

    def swipe(
        self,
        *points: PointLike | float,
        duration_ms: int = 300,
        normalized: bool = False,
    ) -> ActionResult:
        """Swipe through ``(x, y)`` pairs or flat numeric coordinates."""
        return self.session.execute(
            Swipe(_points(points, normalized=normalized), duration_ms=duration_ms)
        )

    def text(self, value: str) -> ActionResult:
        return self.session.execute(InputText(value))

    def key(self, value: KeyCode | str) -> ActionResult:
        return self.session.execute(Key(_key_code(value)))

    def back(self) -> ActionResult:
        return self.key(KeyCode.BACK)

    def home(self) -> ActionResult:
        return self.key(KeyCode.HOME)

    def enter(self) -> ActionResult:
        return self.key(KeyCode.ENTER)

    def screenshot(
        self,
        path: str | Path | None = None,
        *,
        format: ImageFormat | str | None = None,
        quality: int = 90,
        max_width: int = 0,
        max_height: int = 0,
    ) -> Screenshot:
        """Capture a screenshot; call the result's ``ocr()`` when needed."""
        target = None if path is None else Path(path)
        if format is None:
            image_format = (
                ImageFormat.JPEG
                if target is not None and target.suffix.lower() in {".jpg", ".jpeg"}
                else ImageFormat.PNG
            )
        else:
            image_format = _image_format(format)
        result = self.session.screenshot(
            format=image_format,
            quality=quality,
            max_width=max_width,
            max_height=max_height,
        )
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(result.data)
        return replace(result, _ocr_callback=self._ocr_screenshot)

    def locate_icon(
        self,
        template: str | Path | bytes,
        *,
        min_score: float = 0.85,
        region: tuple[int, int, int, int] | None = None,
    ) -> ImageMatch | None:
        """Locate an icon template in a fresh screenshot without tapping it.

        ``template`` is a path or encoded image bytes, preferably cropped from
        this device's screenshot. ``region`` optionally limits matching to an
        ``(x, y, width, height)`` screen-pixel rectangle. ``min_score`` is the
        normalized OpenCV matching threshold, not a probability. Returns
        ``None`` when the best match is below the threshold. Install
        ``nier[vision]`` to enable matching.

        The screenshot read follows the session's read retry policy. Locating
        an icon is read-only and never performs a device action.
        """
        screenshot = self.screenshot()
        match = locate_template(
            screenshot.data,
            template,
            min_score=min_score,
            region=region,
        )
        return None if match is None else self._bind_image_match(match)

    def locate_text(
        self,
        text: str,
        *,
        min_score: float = 0.6,
    ) -> ImageMatch | None:
        """Locate OCR text in one fresh screenshot using fuzzy similarity.

        The first configured OCR provider recognizes the screenshot. Text is
        normalized with Unicode NFKC and case-folding, then compared to each
        OCR span with ``SequenceMatcher``. The best span meeting ``min_score``
        is returned as a screen-coordinate :class:`ImageMatch`; its ``score``
        is text similarity from 0 to 1, not a probability. The returned match
        is bound to this device, so ``match.click()`` taps its center once.

        OCR must be configured through ``models.ocr`` or
        ``models.ocr_providers``. Screenshot reads follow the session retry
        policy; OCR and locating do not perform a device action.
        """
        query = _normalize_locator_text(text)
        _validate_text_score(min_score)
        screenshot = self.screenshot()
        best: ImageMatch | None = None
        best_score = -1.0
        for span in screenshot.ocr():
            candidate = " ".join(
                normalize("NFKC", span.text).casefold().split()
            )
            if not candidate:
                continue
            score = SequenceMatcher(
                None,
                query,
                candidate,
                autojunk=False,
            ).ratio()
            coordinates = (
                span.box.left,
                span.box.top,
                span.box.right,
                span.box.bottom,
            )
            if not all(isfinite(value) for value in coordinates):
                continue
            left = max(0, min(screenshot.width, floor(span.box.left)))
            top = max(0, min(screenshot.height, floor(span.box.top)))
            right = max(0, min(screenshot.width, ceil(span.box.right)))
            bottom = max(0, min(screenshot.height, ceil(span.box.bottom)))
            if right <= left or bottom <= top:
                continue
            if score > best_score:
                best_score = score
                best = ImageMatch(
                    x=left,
                    y=top,
                    width=right - left,
                    height=bottom - top,
                    score=score,
                )
        if best is None or best.score < min_score:
            return None
        return self._bind_image_match(best)

    def _bind_image_match(self, match: ImageMatch) -> ImageMatch:
        center = match.center

        def clicker(duration_ms: int) -> ActionResult:
            return self.click(*center, duration_ms=duration_ms)

        return replace(match, _clicker=clicker)

    def _ocr_screenshot(self, image: bytes) -> Sequence[TextSpan]:
        """Run the first configured OCR provider on screenshot bytes."""
        provider = self._configured_provider_name(
            self.app_config.models.ocr_providers if self.app_config is not None else {},
            None,
        )
        step("ocr", provider=provider, image_bytes=len(image))
        return self._cached_ocr_provider(provider).recognize(image)

    def dump_ui(
        self,
        *,
        prefer_webview: bool = True,
        include_invisible: bool = False,
    ) -> UiDump:
        """Return the complete UI dump result, including source metadata."""
        return self.session.dump_ui(
            prefer_webview=prefer_webview,
            include_invisible=include_invisible,
        )

    def uidump(
        self,
        path: str | Path | None = None,
        *,
        prefer_webview: bool = True,
        include_invisible: bool = False,
    ) -> str:
        """Return UI XML/HTML and optionally save it to ``path``."""
        result = self.dump_ui(
            prefer_webview=prefer_webview,
            include_invisible=include_invisible,
        )
        if path is not None:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.xml, encoding="utf-8")
        return result.xml

    def parse_uidump(
        self,
        dump: str | Path | UiDump | None = None,
        *,
        prefer_webview: bool = True,
        include_invisible: bool = False,
    ) -> UiDocument:
        """Capture or parse a UI dump and return searchable nodes.

        With no ``dump`` argument, a fresh dump is captured. A string is
        treated as XML/HTML content; pass a ``Path`` to read a saved dump.
        """
        if dump is None:
            return parse_ui_dump(
                self.dump_ui(
                    prefer_webview=prefer_webview,
                    include_invisible=include_invisible,
                )
            )
        return parse_ui_dump(dump)

    def widgets(
        self,
        dump: str | Path | UiDump | UiDocument | None = None,
        *,
        prefer_webview: bool = False,
        include_invisible: bool = False,
    ) -> WidgetList:
        """Capture or parse a UI dump as device-bound, chainable widgets.

        With no ``dump`` argument, capture one UI dump. Pass an existing
        ``UiDocument``, ``UiDump``, XML/HTML string, or saved path to reuse it.
        Use ``widgets.clickable().choice(instruction).click()`` to let the
        configured TypeSafe Choice provider select a visible control. The
        ``clickable()`` filter is optional; ``choice()`` itself excludes
        candidates that cannot safely be clicked. UIAutomator is preferred by
        default because it supplies clickable flags and screen-space bounds;
        WebView DOM nodes without those bounds cannot be tapped by this chain.
        """
        if isinstance(dump, UiDocument):
            document = dump
        else:
            document = self.parse_uidump(
                dump,
                prefer_webview=prefer_webview,
                include_invisible=include_invisible,
            )
        return WidgetList(self, document.walk(), source=document.source)

    def format_tree(
        self,
        root: UiNode | UiDocument,
        *,
        color: bool = True,
    ) -> str:
        """Render a compact UI tree with true attributes and optional ANSI color.

        ``root`` may be a parsed :class:`UiNode` or its containing
        :class:`UiDocument`. Text is shortened for readability. Attributes
        whose values are false or non-boolean are omitted. Set ``color=False``
        when saving the result to a text file.
        """
        if isinstance(root, UiDocument):
            node = root.root
        elif isinstance(root, UiNode):
            node = root
        else:
            raise TypeError("root must be a UiNode or UiDocument")
        return _format_tree(node, color=color)

    def choice(
        self,
        state: Any,
        options: SysOneOptions | None = None,
        *,
        instructions: Any,
        question_id: str = "choice",
        criteria: SysOneOptions | None = None,
        provider: str | None = None,
        router: ModelRouter | None = None,
    ) -> SysOneAnswer:
        """Ask TypeSafe Choice to select among explicit options.

        ``options`` may be a sequence of labels or a mapping from stable option
        IDs to descriptions. Pass ``criteria`` as an alternative keyword. The
        configured TypeSafe provider is created lazily and cached. ``router``
        and ``provider`` select an existing model provider explicitly.
        """
        return self._sysone_client(provider=provider, router=router).choice(
            state,
            options,
            instructions=instructions,
            question_id=question_id,
            criteria=criteria,
        )

    def noul(
        self,
        state: Any,
        *,
        instructions: Any,
        question_id: str = "noul",
        criteria: Any = (),
        provider: str | None = None,
        router: ModelRouter | None = None,
    ) -> SysOneAnswer:
        """Ask TypeSafe Noul for a normalized truth-value score."""
        return self._sysone_client(provider=provider, router=router).noul(
            state,
            instructions=instructions,
            question_id=question_id,
            criteria=criteria,
        )

    def score(
        self,
        state: Any,
        criteria: Sequence[Any],
        *,
        instructions: Any,
        question_id: str = "score",
        provider: str | None = None,
        router: ModelRouter | None = None,
    ) -> SysOneAnswer:
        """Ask TypeSafe Score to rate state against ordered criteria."""
        return self._sysone_client(provider=provider, router=router).score(
            state,
            criteria,
            instructions=instructions,
            question_id=question_id,
        )

    def _sysone_client(
        self,
        *,
        provider: str | None = None,
        router: ModelRouter | None = None,
    ) -> SysOneProvider:
        if router is not None:
            try:
                return router.sysone(provider=provider)
            except KeyError as exc:
                available = ", ".join(sorted(router.sysone_providers))
                raise ModelError(
                    f"unknown SysOne provider {provider!r}; available: {available or 'none'}"
                ) from exc
        return self._cached_sysone(provider)

    def sysone_goal(
        self,
        *,
        router: ModelRouter | None = None,
        ocr_provider: str | None = None,
        sysone: SysOneProvider | None = None,
        sysone_provider: str | None = None,
        llm: LlmProvider | None = None,
        llm_provider: str | None = None,
        max_steps: int = 8,
        max_seconds: float | None = None,
        done_threshold: float = 0.85,
        action_threshold: float = 0.65,
        max_candidates: int = 32,
        allowed_apps: Mapping[str, str] | None = None,
        allowed_controls: Sequence[str] | None = None,
        denied_controls: Sequence[str] = (),
        use_score: bool = False,
        prefer_webview: bool = True,
        max_llm_assists: int | None = None,
    ) -> SysOneGoal:
        """Create a bounded goal runner driven primarily by SysOne.

        SysOne chooses among a bounded UI/OCR/app candidate list and the host
        executes only its selected, validated candidate. If an LLM is available,
        SysOne may choose ``call_llm`` or a failed run may request a bounded
        recovery subgoal. The LLM executes it by selecting only safe,
        host-validated dismiss/cancel/skip/back/home controls; it cannot supply
        coordinates or arbitrary device operations. If a recovery subgoal fails,
        the LLM may generate a replacement using a fresh observation. The default has no
        assist-count limit; pass a non-negative ``max_llm_assists`` to cap it,
        or zero to disable LLM recovery. The first configured SysOne, LLM, and OCR
        providers are selected when names are omitted. A configured OCR provider runs only after SysOne
        selects ``inspect_ocr`` and at most once per observation.
        Set ``prefer_webview=False`` for native screens to avoid probing WebView
        DevTools before falling back to UIAutomator.
        Dry-run previews and non-action decisions do not make a second UI dump;
        a fresh observation is still required immediately before a real action.
        Main-goal actions are bounded by ``max_steps``. The overall time limit
        is disabled when ``max_seconds`` is ``None``; an explicit limit may be
        up to 60 seconds. Recovery subgoals have a separate limit of three
        actions and thirty seconds, further bounded by the remaining main-goal
        deadline when one is set. SysOne only selects from
        host-generated candidates; it cannot provide text or
        coordinates. ``allowed_controls`` and ``denied_controls`` match exact
        UI/OCR/system labels after case and whitespace normalization.
        ``allowed_apps`` maps display labels to validated Android package names;
        these app-launch candidates are omitted by default and SysOne sees only
        their label and candidate ID. It cannot supply an arbitrary package.
        ``use_score`` adds optional progress telemetry. An explicit
        ``max_seconds`` prevents another action after its deadline, but cannot
        interrupt an in-flight provider or device call.
        A Noul completion signal returns ``needs_verification`` for independent
        caller review.
        """
        from .sysone_goal import SysOneGoal

        if sysone is not None and sysone_provider is not None:
            raise ValueError("pass either sysone= or sysone_provider=, not both")
        if llm is not None and llm_provider is not None:
            raise ValueError("pass either llm= or llm_provider=, not both")

        selected_sysone_provider = sysone_provider
        if sysone is None:
            if router is not None:
                if selected_sysone_provider is None:
                    selected_sysone_provider = next(iter(router.sysone_providers), None)
                try:
                    sysone = router.sysone(provider=selected_sysone_provider)
                except KeyError as exc:
                    available = ", ".join(sorted(router.sysone_providers))
                    raise ModelError(
                        f"unknown SysOne provider {selected_sysone_provider!r}; available: {available or 'none'}"
                    ) from exc
            else:
                selected_sysone_provider = self._configured_provider_name(
                    self.app_config.models.sysone_providers
                    if self.app_config is not None
                    else {},
                    selected_sysone_provider,
                )
                sysone = self._cached_sysone(selected_sysone_provider)
        elif selected_sysone_provider is None:
            selected_sysone_provider = "custom"

        selected_llm_provider = llm_provider
        if llm is None:
            if router is not None:
                if selected_llm_provider is None:
                    selected_llm_provider = next(iter(router.llm_providers), None)
                if selected_llm_provider is not None:
                    try:
                        llm = router.llm_providers[selected_llm_provider]
                    except KeyError as exc:
                        available = ", ".join(sorted(router.llm_providers))
                        raise ModelError(
                            f"unknown LLM provider {selected_llm_provider!r}; "
                            f"available: {available or 'none'}"
                        ) from exc
            elif self.app_config is not None:
                named_llm = self.app_config.models.llm_providers
                if selected_llm_provider is None and named_llm:
                    selected_llm_provider = next(iter(named_llm))
                if selected_llm_provider is not None:
                    llm_provider_name = selected_llm_provider
                    llm = _LazyLlmProvider(
                        lambda: self._configured_llm(llm_provider_name)
                    )
                elif self.app_config.models.llm.api_key is not None:
                    selected_llm_provider = "default"
                    llm = _LazyLlmProvider(
                        lambda: self._configured_llm("default")
                    )
            elif selected_llm_provider is not None:
                llm_provider_name = selected_llm_provider
                llm = _LazyLlmProvider(
                    lambda: self._configured_llm(llm_provider_name)
                )
        elif selected_llm_provider is None:
            selected_llm_provider = "custom"

        ocr: OcrProvider | None = None
        selected_ocr_provider = ocr_provider
        if selected_ocr_provider is None:
            if router is not None:
                selected_ocr_provider = next(iter(router.ocr_providers), None)
            elif self.app_config is not None:
                selected_ocr_provider = next(
                    iter(self.app_config.models.ocr_providers),
                    None,
                )
        if selected_ocr_provider is not None:
            if router is not None:
                try:
                    ocr = router.ocr_providers[selected_ocr_provider]
                except KeyError as exc:
                    available = ", ".join(sorted(router.ocr_providers))
                    raise ModelError(
                        f"unknown OCR provider {selected_ocr_provider!r}; available: {available or 'none'}"
                    ) from exc
            else:
                ocr_provider_name = selected_ocr_provider
                ocr = _LazyOcrProvider(
                    lambda: self._cached_ocr_provider(ocr_provider_name)
                )

        return SysOneGoal(
            self,
            sysone,
            provider=selected_sysone_provider,
            ocr=ocr,
            max_steps=max_steps,
            max_seconds=max_seconds,
            done_threshold=done_threshold,
            action_threshold=action_threshold,
            max_candidates=max_candidates,
            allowed_apps=allowed_apps,
            allowed_controls=allowed_controls,
            denied_controls=denied_controls,
            use_score=use_score,
            prefer_webview=prefer_webview,
            llm=llm,
            llm_provider=selected_llm_provider,
            max_llm_assists=max_llm_assists,
        )

    def agent(
        self,
        *,
        provider: str | None = None,
        llm: LlmProvider | None = None,
        router: ModelRouter | None = None,
        ocr_provider: str | None = None,
        sysone: SysOneProvider | None = None,
        sysone_provider: str | None = None,
        max_steps: int = 8,
    ) -> Agent:
        """Create an iterative LLM goal agent for this device.

        A configured LLM is loaded from the first configured provider when
        ``provider`` is omitted. The first configured OCR provider is used
        when ``ocr_provider`` is omitted. SysOne is advisory and opt-in: pass
        ``sysone=`` or ``sysone_provider=`` to include it in the planner context.
        The Agent re-observes after each action until the goal terminates. A
        direct ``sysone`` client can also be supplied. For interactive
        debugging, call ``agent.debug(goal)`` and
        explicitly invoke its ``step()`` method to execute and inspect one
        action at a time.
        """
        from .agent import Agent

        if llm is not None and router is not None:
            raise ValueError("pass either llm or router, not both")
        if sysone is not None and sysone_provider is not None:
            raise ValueError("pass either sysone= or sysone_provider=, not both")
        selected_provider = provider
        if router is not None:
            if selected_provider is None:
                try:
                    selected_provider = select_provider_name(router.llm_providers)
                except KeyError as exc:
                    raise ModelError("no LLM providers are configured") from exc
            try:
                llm = router.llm_providers[selected_provider]
            except KeyError as exc:
                available = ", ".join(sorted(router.llm_providers))
                raise ModelError(
                    f"unknown LLM provider {selected_provider!r}; available: {available}"
                ) from exc
        if llm is None:
            selected_provider = self._configured_provider_name(
                self.app_config.models.llm_providers
                if self.app_config is not None
                else {},
                selected_provider,
            )
            llm = self._configured_llm(selected_provider)
        elif selected_provider is None:
            selected_provider = "custom"

        ocr: OcrProvider | None = None
        selected_ocr_provider = ocr_provider
        if selected_ocr_provider is None:
            if router is not None:
                selected_ocr_provider = next(iter(router.ocr_providers), None)
            elif self.app_config is not None:
                selected_ocr_provider = next(
                    iter(self.app_config.models.ocr_providers),
                    None,
                )
        if selected_ocr_provider is not None:
            if router is not None:
                try:
                    ocr = router.ocr_providers[selected_ocr_provider]
                except KeyError as exc:
                    available = ", ".join(sorted(router.ocr_providers))
                    raise ModelError(
                        f"unknown OCR provider {selected_ocr_provider!r}; available: {available}"
                    ) from exc
            else:
                ocr = _LazyOcrProvider(
                    lambda: self._cached_ocr_provider(selected_ocr_provider)
                )

        if sysone is None:
            selected_sysone_provider = sysone_provider
            if selected_sysone_provider is not None:
                if router is not None:
                    try:
                        sysone = router.sysone(provider=selected_sysone_provider)
                    except KeyError as exc:
                        available = ", ".join(sorted(router.sysone_providers))
                        raise ModelError(
                            f"unknown SysOne provider {selected_sysone_provider!r}; available: {available or 'none'}"
                        ) from exc
                else:
                    sysone = self._cached_sysone(selected_sysone_provider)
        return Agent(
            self,
            llm,
            provider=selected_provider,
            ocr=ocr,
            sysone=sysone,
            max_steps=max_steps,
        )

    def llm(
        self,
        instruction: str,
        *,
        provider: str | None = None,
        llm: LlmProvider | None = None,
        router: ModelRouter | None = None,
        ocr_provider: str | None = None,
        sysone: SysOneProvider | None = None,
        sysone_provider: str | None = None,
        max_steps: int = 8,
        dry_run: bool = False,
    ) -> AgentRun:
        """Run a natural-language goal with LLM planning and validated tools.

        The LLM observes the current screenshot and UI state, then chooses one
        validated device operation per step. SysOne may be added as typed
        advisory context by passing ``sysone`` or ``sysone_provider``. To use
        SysOne as the primary selector, call :meth:`sysone`.
        """
        return self.agent(
            provider=provider,
            llm=llm,
            router=router,
            ocr_provider=ocr_provider,
            sysone=sysone,
            sysone_provider=sysone_provider,
            max_steps=max_steps,
        ).run(instruction, dry_run=dry_run)

    def sysone(
        self,
        instruction: str,
        *,
        router: ModelRouter | None = None,
        ocr_provider: str | None = None,
        sysone: SysOneProvider | None = None,
        sysone_provider: str | None = None,
        max_steps: int = 8,
        max_seconds: float | None = None,
        done_threshold: float = 0.85,
        action_threshold: float = 0.65,
        max_candidates: int = 32,
        allowed_apps: Mapping[str, str] | None = None,
        allowed_controls: Sequence[str] | None = None,
        denied_controls: Sequence[str] = (),
        use_score: bool = False,
        prefer_webview: bool = True,
        llm: LlmProvider | None = None,
        llm_provider: str | None = None,
        max_llm_assists: int | None = None,
        dry_run: bool = False,
    ) -> AgentRun:
        """Run a goal with SysOne selecting from validated UI/OCR candidates.

        The overall goal deadline is disabled by default. Pass ``max_seconds``
        to enable a positive deadline of up to 60 seconds.

        ``allowed_apps`` explicitly allowlists app launches by display label
        and package name. ``allowed_controls`` and ``denied_controls`` restrict
        UI/OCR/system candidate labels.
        A configured OCR provider runs only after SysOne selects ``inspect_ocr``.
        SysOne may select ``call_llm`` or a failed run may request a bounded
        recovery subgoal. The LLM can execute it only by choosing from safe,
        host-validated controls; it cannot supply arbitrary device actions.
        Set ``prefer_webview=False`` for native screens to avoid probing WebView
        DevTools before falling back to UIAutomator.
        Dry-run previews and non-action decisions do not make a second UI dump;
        a fresh observation is still required immediately before a real action.
        A completion decision returns ``needs_verification`` for the caller to
        check independently. Use :meth:`llm` for LLM-first planning.
        """
        return self.sysone_goal(
            router=router,
            ocr_provider=ocr_provider,
            sysone=sysone,
            sysone_provider=sysone_provider,
            llm=llm,
            llm_provider=llm_provider if llm is None else None,
            max_steps=max_steps,
            max_seconds=max_seconds,
            done_threshold=done_threshold,
            action_threshold=action_threshold,
            max_candidates=max_candidates,
            allowed_apps=allowed_apps,
            allowed_controls=allowed_controls,
            denied_controls=denied_controls,
            use_score=use_score,
            prefer_webview=prefer_webview,
            max_llm_assists=max_llm_assists,
        ).run(instruction, dry_run=dry_run)

    def _configured_llm(self, provider: str) -> LlmProvider:
        if self.app_config is None:
            raise ConfigurationError(
                "no model configuration is attached; pass llm= or router= to device.agent()"
            )
        spec = self.app_config.models.llm_providers.get(provider)
        if spec is None and (provider == "default" or not self.app_config.models.llm_providers):
            spec = self.app_config.models.llm
        if spec is None:
            available = ", ".join(sorted(self.app_config.models.llm_providers))
            raise ConfigurationError(f"unknown LLM provider {provider!r}; available: {available}")
        if spec.provider != "openai-compatible":
            raise ModelError(f"unsupported LLM provider: {spec.provider}")
        from .models.llm import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            base_url=spec.base_url,
            api_key=spec.api_key,
            model=spec.model,
            timeout=spec.timeout_seconds,
        )

    def _configured_ocr(self, provider: str) -> OcrProvider:
        if self.app_config is None:
            raise ConfigurationError(
                "no model configuration is attached; pass router= to device.agent()"
            )
        spec = self.app_config.models.ocr_providers.get(provider)
        if spec is None and (provider == "default" or not self.app_config.models.ocr_providers):
            spec = self.app_config.models.ocr
        if spec is None:
            available = ", ".join(sorted(self.app_config.models.ocr_providers))
            raise ConfigurationError(f"unknown OCR provider {provider!r}; available: {available}")
        if spec.provider == "paddleocr":
            from .models.ocr import PaddleOcrProvider

            return PaddleOcrProvider(lang=spec.lang)
        if spec.provider in {"paddleocr-api", "paddleocr-online"}:
            from .models.ocr import PaddleOcrApiProvider

            return PaddleOcrApiProvider(
                lang=spec.lang,
                api_key=spec.api_key,
                api_key_env=spec.api_key_env,
                base_url=spec.base_url,
                model=spec.model,
                request_timeout=spec.request_timeout_seconds,
                poll_timeout=spec.poll_timeout_seconds,
            )
        if spec.provider in {"paddleocr-compatible", "paddleocr-local-api"}:
            from .models.ocr import PaddleOcrCompatibleApiProvider

            if not spec.base_url:
                raise ModelError(
                    f"OCR provider {spec.provider!r} requires models.ocr.base_url"
                )
            return PaddleOcrCompatibleApiProvider(
                base_url=spec.base_url,
                request_timeout=spec.request_timeout_seconds,
            )
        raise ModelError(f"unsupported OCR provider: {spec.provider}")

    def _cached_ocr_provider(self, provider: str) -> OcrProvider:
        provider = self._configured_provider_name(
            self.app_config.models.ocr_providers if self.app_config is not None else {},
            provider,
        )
        cached = self._ocr_cache.get(provider)
        if cached is not None:
            return cached
        created = self._configured_ocr(provider)
        self._ocr_cache[provider] = created
        return created

    def _configured_sysone(self, provider: str) -> SysOneProvider:
        if self.app_config is None:
            raise ConfigurationError(
                "no model configuration is attached; pass router= to "
                "device.choice(), device.noul(), or device.score()"
            )
        spec = self.app_config.models.sysone_providers.get(provider)
        if spec is None and (provider == "default" or not self.app_config.models.sysone_providers):
            spec = self.app_config.models.sysone
        if spec is None:
            available = ", ".join(sorted(self.app_config.models.sysone_providers))
            raise ConfigurationError(f"unknown SysOne provider {provider!r}; available: {available}")
        if spec.provider != "typesafe":
            raise ModelError(f"unsupported SysOne provider: {spec.provider}")
        from .models.sysone import SysOneProvider

        return SysOneProvider(
            base_url=spec.base_url,
            api_key=spec.api_key,
            api_key_env=spec.api_key_env,
            model=spec.model,
            timeout=spec.timeout_seconds,
        )

    def _cached_sysone(self, provider: str | None) -> SysOneProvider:
        provider = self._configured_provider_name(
            self.app_config.models.sysone_providers if self.app_config is not None else {},
            provider,
        )
        cached = self._sysone_cache.get(provider)
        if cached is not None:
            return cached
        created = self._configured_sysone(provider)
        self._sysone_cache[provider] = created
        return created

    @staticmethod
    def _configured_provider_name(
        providers: Mapping[str, object], provider: str | None
    ) -> str:
        """Use an explicit name or the first configured name.

        The singular model sections remain available as the ``default``
        fallback when no named provider mapping is present.
        """
        if provider is not None:
            return provider
        return next(iter(providers), "default")

    def save_run(self, filename: str = "run.json") -> Path:
        return self.session.recorder.write_json(filename)

    def close(self) -> None:
        try:
            self.session.close()
        finally:
            providers = tuple((*self._ocr_cache.values(), *self._sysone_cache.values()))
            self._ocr_cache.clear()
            self._sysone_cache.clear()
            for provider in providers:
                close = getattr(provider, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass


def connect(
    config: str | Path | AppConfig | None = None,
    *,
    serial: str | None = None,
    remote: Endpoint | None = None,
    adb_server: Endpoint | None = None,
    adb_path: str | None = None,
    retries: int | None = None,
    output_dir: str | Path | None = None,
    timeout: float | None = None,
) -> Device:
    """Connect to a local, USB, or remote-ADB Android device.

    ``connect()`` uses local ADB defaults. Pass a YAML path to reuse project
    configuration, ``serial=`` for one attached device, or ``remote=`` for an
    ADB-over-TCP endpoint such as ``"192.168.1.20:5555"``.
    """
    if serial is not None and remote is not None:
        raise ValueError("serial and remote are mutually exclusive")
    if isinstance(config, AppConfig):
        app = config
    elif config is not None:
        app = load_config(config)
    else:
        app = AppConfig()
    device_config = app.device
    runtime_config = app.runtime

    overrides: dict[str, object] = {}
    if serial is not None:
        overrides.update(serial=serial, remote_host=None)
    if remote is not None:
        host, port = _endpoint(remote, 5555)
        overrides.update(serial=None, remote_host=host, remote_port=port)
    if adb_server is not None:
        host, port = _endpoint(adb_server, 5037)
        overrides.update(adb_server_host=host, adb_server_port=port)
    if adb_path is not None:
        overrides["adb_path"] = adb_path
    if timeout is not None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        overrides["connect_timeout_seconds"] = timeout
    if overrides:
        device_config = replace(device_config, **overrides)

    retry_count = runtime_config.retries if retries is None else retries
    if retry_count < 0:
        raise ValueError("retries must not be negative")
    artifact_dir = runtime_config.output_dir if output_dir is None else Path(output_dir)
    recorder = RunRecorder(artifact_dir)
    session = DeviceSession(
        AdbBackend(
            device_config,
            hook_config=app.hook,
            input_text_config=app.input_text,
        ),
        retries=retry_count,
        recorder=recorder,
    )
    return Device(session, output_dir=artifact_dir, app_config=app)
