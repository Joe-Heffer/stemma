class StemmaError(Exception):
    """An error with a message fit to show the user, without a traceback."""


class BackendUnavailable(StemmaError):
    """A required external tool or sound file is missing."""
