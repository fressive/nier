"""Errors shared by the Nier runtime."""


class NierError(Exception):
    """Base class for expected Nier failures."""


class ConfigurationError(NierError):
    """The application configuration is invalid."""


class BackendError(NierError):
    """A backend operation failed."""


class BackendUnavailable(BackendError):
    """The backend cannot currently be reached."""


class ProtocolError(BackendError):
    """The backend returned data that violates the protocol contract."""


class UiElementNotFound(NierError):
    """No UI label match with usable screen bounds was found."""


class ModelError(NierError):
    """A model provider failed or returned an invalid result."""


class HookError(NierError):
    """A device or application instrumentation operation failed."""


class HookUnavailable(HookError):
    """The selected hook mode cannot instrument the target in this environment."""


class VisionUnavailable(NierError):
    """An optional image-recognition dependency is unavailable."""
