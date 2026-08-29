"""Control-flow exceptions (mini-swe-agent style)."""


class InterruptAgentFlow(Exception):
    """Base for intentional loop interrupts. Carry messages to append."""

    def __init__(self, *messages: dict):
        self.messages = list(messages)
        super().__init__(self.messages)


class Submitted(InterruptAgentFlow):
    """Task finished; environment or agent submitted an answer."""


class LimitsExceeded(InterruptAgentFlow):
    """Step or cost limit hit."""


class TimeExceeded(InterruptAgentFlow):
    """Wall-clock limit hit."""


class FormatError(InterruptAgentFlow):
    """Model output could not be parsed into a valid action."""


class Interrupted(InterruptAgentFlow):
    """User stopped the current turn; session stays alive."""
