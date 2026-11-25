"""Application-specific exceptions."""
class Quit(Exception):
    """Raised when the user quits an interactive screen."""


class YTError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint
