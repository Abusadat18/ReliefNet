"""Indian mobile numbers: clean up what people type and compare them.

People type +91, 0, spaces, dashes and Devanagari digits. We keep the last ten
digits, which is what two numbers must share to be the same phone."""
from __future__ import annotations

import re
import unicodedata

_SEPARATORS = re.compile(r"[\s\-().]")


def _ascii_digits(raw: str) -> str:
    """Keep digits only, turning Devanagari and other Unicode digits into 0-9."""
    out = []
    for ch in _SEPARATORS.sub("", raw):
        if ch == "+":
            continue
        if ch.isdigit():
            out.append(str(unicodedata.digit(ch)))
        else:
            return ""  # letters or symbols: not a phone number
    return "".join(out)


def normalize(raw: str | None) -> str | None:
    """Return the ten-digit mobile number, or None if it is not a valid one.

    Accepts "+91 98765-43210", "09876543210", "919876543210" and "९८७६५ ४३२१०".
    Indian mobile numbers have ten digits and start with 6, 7, 8 or 9."""
    digits = _ascii_digits(raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return None


def mask(phone: str | None) -> str:
    """98xxxxxx21: enough for a coordinator to recognise, not enough to copy."""
    if not phone or len(phone) < 4:
        return ""
    return phone[:2] + "x" * (len(phone) - 4) + phone[-2:]


def same(a: str | None, b: str | None) -> bool:
    na, nb = normalize(a), normalize(b)
    return bool(na) and na == nb
