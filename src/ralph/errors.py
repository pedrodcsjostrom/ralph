class RalphError(Exception):
    """A reason to stop. The message is shown to the runner as is, after "ralph: "."""


class AlreadyReported(RalphError):
    """A stop already shown to the runner, ending the command with status."""

    def __init__(self, status: int):
        super().__init__(f"stopped with status {status}")
        self.status = status
