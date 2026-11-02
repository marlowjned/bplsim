"""Error types. Every user-facing error carries a location when one is known."""
from __future__ import annotations


class BplsimError(Exception):
    """Base class for all bplsim errors."""


class ConfigError(BplsimError):
    """A problem in a library entry, study or site file."""

    def __init__(self, message: str, file: str | None = None, line: int | None = None,
                 path: str | None = None):
        self.message, self.file, self.line, self.path = message, file, line, path
        super().__init__(self.format())

    def format(self) -> str:
        loc = ""
        if self.file:
            loc = str(self.file) + (f":{self.line}" if self.line else "") + ": "
        where = f"{self.path}: " if self.path else ""
        return f"{loc}{where}{self.message}"


class ErrorList(BplsimError):
    """Several errors reported together (bplsim check reports all errors, not just the first)."""

    def __init__(self, errors: list[BaseException]):
        self.errors = errors
        super().__init__("\n".join(str(e) for e in errors))


class ExpressionError(ConfigError):
    pass


class ResolveError(ConfigError):
    pass


class BackendError(BplsimError):
    pass
