"""Errors shared by every layer."""


class YyaiError(Exception):
    """Base class for all yyai errors."""


class ConfigError(YyaiError):
    """The client config is missing something or is invalid."""


class SignatureError(YyaiError):
    """An incoming webhook failed its signature check."""


class IntegrationError(YyaiError):
    """An outside system (vendor, model server, messaging provider) failed.

    `retryable` tells the caller whether trying again later can help.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ExternalModelNotAllowed(YyaiError):
    """A model role points outside the building but the config forbids it."""


class WindowClosed(YyaiError):
    """WhatsApp's 24-hour window is closed: only template messages may be sent."""


class NotFound(YyaiError):
    """A requested record does not exist."""
