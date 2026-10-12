"""Errors a graph can raise to end its run with a clean, user-safe message."""


class RunError(Exception):
    """Ends the run with an `error` event carrying `code`, `message` and `retryable`.

    `message` is shown to users: no stack traces, hostnames or model output.
    """

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable
