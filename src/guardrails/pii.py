"""Regex-based PII masking.

No LLM call: masking is local and free, run on every message before it reaches an LLM or a
trace/log (see the Cost controls section in the README — PII masking is budgeted at $0.00 for
exactly this reason). Order matters: card numbers are matched before phone numbers so a
16-digit card isn't first chopped into a phone-shaped prefix.
"""

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "CARD": re.compile(r"(?<!\d)\d(?:[ -]?\d){12,15}(?!\d)"),  # ends on a digit, never swallows a trailing separator
    "SSN": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "PHONE": re.compile(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"),
}


def mask_pii(text: str) -> str:
    masked = text
    for label, pattern in _PATTERNS.items():
        masked = pattern.sub(f"[REDACTED_{label}]", masked)
    return masked


class RegexPIIMasker:
    async def mask(self, text: str) -> str:
        return mask_pii(text)
