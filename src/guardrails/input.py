from src.core.errors import GuardrailViolation

# TODO(guardrails): replace with a real guardrails library / classifier.
_BLOCKED_PHRASES = ("ignore previous instructions", "ignore all previous instructions", "reveal your system prompt")


def check_input(message: str) -> None:
    lowered = message.lower()
    for phrase in _BLOCKED_PHRASES:
        if phrase in lowered:
            raise GuardrailViolation("Message rejected by input guardrails.")
