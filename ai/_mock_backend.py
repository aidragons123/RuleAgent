"""
ai/_mock_backend.py

NOT one of the four abstract methods you implement (those are
test_synthesis.py, implementation.py, divergence.py, evidence.py).
This is shared, deterministic domain logic used ONLY by the offline
"mock" LLM backend (platform/llm_client.py, mode=mock) so the demo
runs end to end with no API key. In "real" mode none of this file is
consulted — the rendered prompts in ai/prompts/*.md go to the model
instead, and its JSON answer is used verbatim.

Kept separate from the four files above so it's obvious, on a read of
this repo, which code is "the AI's judgement calls" (the four files)
and which is "a stand-in transport for a real model" (this file).
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

OVERPUNCH_POS = "{ABCDEFGHI"
OVERPUNCH_NEG = "}JKLMNOPQR"


def overpunch_encode(magnitude_cents: int, negative: bool) -> str:
    """magnitude_cents: 7-digit unsigned integer, e.g. 123456 -> '0123456'.
    Returns the 8-char wire field: 7 digit chars + 1 overpunch char
    encoding sign + final digit (the 7th digit char is irrelevant -
    the oracle overwrites it with the decoded digit)."""
    digits = f"{magnitude_cents:07d}"
    last = int(digits[-1])
    table = OVERPUNCH_NEG if negative else OVERPUNCH_POS
    return digits[:7] + table[last]


def overpunch_decode(raw: str) -> str:
    """Mirrors the decode INTCALC.cbl performs, for use by the mock
    implementation generator only (it needs to emit Python source that
    does this - this function IS that logic, written once here and
    also inlined as source text in implementation.py's mock branch)."""
    last = raw[-1]
    if last in OVERPUNCH_POS:
        sign, digit = "+", OVERPUNCH_POS.index(last)
    elif last in OVERPUNCH_NEG:
        sign, digit = "-", OVERPUNCH_NEG.index(last)
    else:
        raise ValueError(f"bad overpunch char {last!r}")
    digits = raw[:6] + str(digit)  # first 6 digit chars unchanged, 7th replaced
    value = Decimal(digits) / 100
    if value == 0:
        sign = "+"
    return f"{sign}{value:08.2f}"


def resolve_year(yy: int) -> int:
    return 1900 + yy if yy >= 50 else 2000 + yy


def tier_and_rate_cobol(balance: Decimal) -> tuple[int, Decimal]:
    """The ORACLE's own boundary semantics (strict >), used only to
    help test-synthesis pick smart boundary values - never used as a
    substitute for actually running the oracle (G1)."""
    if balance > Decimal("10000.00"):
        return 3, Decimal("0.030")
    if balance > Decimal("1000.00"):
        return 2, Decimal("0.020")
    return 1, Decimal("0.010")


def round_half_up(value: Decimal, places: str = "0.01") -> Decimal:
    """COBOL ROUNDED semantics: half away from zero."""
    from decimal import ROUND_HALF_UP
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def round_half_even(value: Decimal, places: str = "0.01") -> Decimal:
    """A naive, individually-defensible reading of "round to the
    nearest cent" that a reasonable implementation might pick - and
    that disagrees with COBOL exactly on ties. This is what makes the
    R-009 divergence real rather than staged."""
    return value.quantize(Decimal(places), rounding=ROUND_HALF_EVEN)
