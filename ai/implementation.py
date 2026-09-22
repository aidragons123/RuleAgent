"""
ai/implementation.py — YOU IMPLEMENT THIS.

ImplementationAI.generate(rules, sig, tests) -> AIResult[SourceFile]

Generates the modernised Java reimplementation from the rules and the
IO signature only (input vectors are given for shape; golden outputs
are never given - guardrail G1). Every method below carries a rule-id
citation; nothing is implemented that isn't backed by one.

The generated class is compiled with `javac` and run as its own
subprocess per test vector (core/java_runner.py), over the exact same
pipe-delimited wire protocol the real COBOL oracle uses (see
core/cobol_runner.py and data/signature/io_signature.yaml) - so the
"modern" code is judged purely on its observable behaviour, the same
way a real modernised service sitting behind an API would be.
"""
from __future__ import annotations

import os

from ai_platform.ai_contract import AILayer, AIResult
from core.models import BusinessRule, IOSignature, SourceFile, TestVector

_GENERATED_SOURCE = r'''
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * generated/GeneratedIntcalc.java
 *
 * AI-GENERATED reimplementation of data/src/legacy/INTCALC.cbl, produced
 * by ai/implementation.py from validated_rules.yaml and io_signature.yaml
 * ONLY. No golden COBOL output was consulted while writing this file
 * (guardrail G1) - it is scored by core/differential.py against the real
 * oracle, and it is expected to disagree with the oracle in places. Those
 * disagreements are the point of the exercise, not a bug in this file.
 *
 * Wire protocol (data/signature/io_signature.yaml): reads one
 * pipe-delimited line from stdin - account_id|balance|
 * adjustment_overpunch|member_since_yy|member_since_mm|member_since_dd -
 * and writes one pipe-delimited line to stdout - tier|interest|
 * adjustment_decoded|effective_year|capped. This is the exact same
 * contract the real COBOL oracle is invoked over (core/cobol_runner.py),
 * so this class is compiled once and run as its own subprocess per
 * vector, never imported in-process - the same arm's-length relationship
 * a real modernised service would have with the legacy system it
 * replaces.
 */
public class GeneratedIntcalc {

    private static final String OVERPUNCH_POS = "{ABCDEFGHI";
    private static final String OVERPUNCH_NEG = "}JKLMNOPQR";

    // R-011: sign and final digit are encoded jointly in the last char.
    // R-012: a decoded zero magnitude is always reported positive.
    static String decodeOverpunch(String raw) {
        char last = raw.charAt(raw.length() - 1);
        String sign;
        int digit;
        int posIdx = OVERPUNCH_POS.indexOf(last);
        int negIdx = OVERPUNCH_NEG.indexOf(last);
        if (posIdx >= 0) {
            sign = "+";
            digit = posIdx;
        } else if (negIdx >= 0) {
            sign = "-";
            digit = negIdx;
        } else {
            throw new IllegalArgumentException("unrecognised overpunch character: " + last);
        }
        String digits = raw.substring(0, 6) + digit; // first 6 digit chars unchanged, 7th replaced
        BigDecimal value = new BigDecimal(digits).movePointLeft(2);
        if (value.compareTo(BigDecimal.ZERO) == 0) {
            sign = "+";
        }
        return sign + String.format("%08.2f", value);
    }

    // R-013: two-digit year window, pivot at 50.
    static int resolveYear(String yyStr) {
        int yy = Integer.parseInt(yyStr.trim());
        return yy >= 50 ? 1900 + yy : 2000 + yy;
    }

    static final class TierRate {
        final int tier;
        final BigDecimal rate;
        TierRate(int tier, BigDecimal rate) { this.tier = tier; this.rate = rate; }
    }

    // R-004, R-005, R-006, R-007, R-008, R-014: three-tier interest.
    // R-016 / R-017: boundary restated as inclusive here - "up to X" is
    // read as balance <= X stays in the lower tier, i.e. the tier
    // changes when balance is STRICTLY GREATER than the ceiling reads
    // naturally as ">=" the next tier's floor. This is one legitimate
    // reading of R-008's own wording; the oracle's COBOL uses strict
    // ">" instead - see the evidence pack's ambiguous-rule findings.
    static TierRate tierAndRate(BigDecimal balance) {
        if (balance.compareTo(new BigDecimal("10000.00")) >= 0) {
            return new TierRate(3, new BigDecimal("0.030"));
        }
        if (balance.compareTo(new BigDecimal("1000.00")) >= 0) {
            return new TierRate(2, new BigDecimal("0.020"));
        }
        return new TierRate(1, new BigDecimal("0.010"));
    }

    // R-009: "rounded to the nearest cent" - the rule text does not
    // specify a half-cent tie-break convention. Banker's rounding
    // (round-half-even) is the IEEE-idiomatic default choice here; it
    // disagrees with COBOL's ROUNDED (half-away-from-zero) on exact
    // ties. See the evidence pack for the ambiguous-rule finding this
    // produces - this is not being hidden or silently "fixed".
    // R-010: always exactly two decimal places.
    static BigDecimal roundInterest(BigDecimal raw) {
        return raw.setScale(2, RoundingMode.HALF_EVEN);
    }

    // R-002 / R-003: balance is a non-negative 2dp decimal; zero is tier 1.
    // R-018: output is emitted as five fields, tier/interest/adjustment/
    // effective_year/capped, in this order.
    // R-019: interest is never negative (guaranteed: rate > 0, balance >= 0).
    // R-022: this method is pure - same input always yields same output.
    static String[] compute(String[] in) {
        BigDecimal balance = new BigDecimal(in[1].trim());
        String adjustmentOverpunch = in[2].trim();
        String memberSinceYy = in[3].trim();

        TierRate tr = tierAndRate(balance);
        BigDecimal rawInterest = balance.multiply(tr.rate);
        BigDecimal interest = roundInterest(rawInterest);

        String adjustmentDecoded = decodeOverpunch(adjustmentOverpunch);
        int effectiveYear = resolveYear(memberSinceYy);

        // No rule in validated_rules.yaml describes any circumstance under
        // which interest is adjusted downward after computation, so no cap
        // is implemented here. If the oracle disagrees, that is exactly
        // the untraceable-behaviour finding this exercise is designed to
        // surface - see the traceability report, not a fix in this file.
        String capped = "N";

        return new String[] {
            String.valueOf(tr.tier),
            interest.toPlainString(),
            adjustmentDecoded,
            String.valueOf(effectiveYear),
            capped,
        };
    }

    public static void main(String[] args) throws Exception {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        String line = reader.readLine();
        if (line == null) {
            System.exit(1);
        }
        String[] in = line.split("\\|", -1);
        String[] out = compute(in);
        System.out.println(String.join("|", out));
    }
}
'''

_CITATIONS = {
    "decodeOverpunch": ["R-011", "R-012"],
    "resolveYear": ["R-013"],
    "tierAndRate": ["R-004", "R-005", "R-006", "R-007", "R-008", "R-014", "R-016", "R-017"],
    "roundInterest": ["R-009", "R-010"],
    "compute": ["R-002", "R-003", "R-018", "R-019", "R-022"],
}

# ---------------------------------------------------------------------------
# Deliberate bug injection - for demoing the two practical scenarios side by
# side: "code generated properly -> VALIDATED report" vs "code has a real
# defect -> INVALIDATED report, correctly caught". Off by default
# (UC04_INJECT_BUG unset = the clean implementation above, unchanged).
#
# Each variant introduces exactly ONE genuine implementation bug into a rule
# that is otherwise fully VALIDATED, so the validation report flips that one
# rule to INVALIDATED_DEFECT (flaw side: code) while every other rule is
# unaffected. This is different from the ambiguous-rule / rounding /
# untraceable-behaviour findings already seeded in the oracle - those are
# legitimate disagreements; this is a plain coding mistake, on purpose, so
# the diagnosis layer has something unambiguous to correctly call a defect.
# ---------------------------------------------------------------------------
BUG_VARIANTS = {
    "tier1_rate": {
        "rule_id": "R-005",
        "description": "Tier-1 interest rate coded as 1.5% instead of 1%.",
        "find": 'return new TierRate(1, new BigDecimal("0.010"));',
        "replace": 'return new TierRate(1, new BigDecimal("0.015")); // BUG: should be 0.010 per R-005',
    },
    "overpunch_table": {
        "rule_id": "R-011",
        "description": "Positive overpunch table has two digit-positions swapped.",
        "find": 'private static final String OVERPUNCH_POS = "{ABCDEFGHI";',
        "replace": 'private static final String OVERPUNCH_POS = "{ABCDEFGIH"; // BUG: digits 8/9 swapped, breaks R-011',
    },
    "year_pivot": {
        "rule_id": "R-013",
        "description": "Year-pivot threshold coded as 60 instead of 50.",
        "find": "return yy >= 50 ? 1900 + yy : 2000 + yy;",
        "replace": "return yy >= 60 ? 1900 + yy : 2000 + yy; // BUG: should be 50 per R-013",
    },
    # Unlike the half-cent tie-break R-009 leaves open - a defensible
    # disagreement, not a defect - this one is unambiguously wrong: it
    # rounds to the nearest DOLLAR, discarding the cents R-009 explicitly
    # asks for. Truncating at the cent instead would only ever be a single
    # cent out, which ai/divergence.py correctly reads as the ambiguous
    # tie-break case (flaw side: rule); this one is off by up to a dollar,
    # so it is diagnosed as what it really is - an implementation defect,
    # flaw side: code. Still emits 2dp, so R-010 stays satisfied and the
    # verdict is unambiguously about R-009.
    "rounding_mode": {
        "rule_id": "R-009",
        "description": "Interest truncated to whole dollars instead of rounded to the nearest cent.",
        "find": "return raw.setScale(2, RoundingMode.HALF_EVEN);",
        "replace": "return raw.setScale(0, RoundingMode.DOWN).setScale(2); "
                   "// BUG: truncates to whole dollars, drops the cents R-009 requires",
    },
}


def _build_source(bug: str | None) -> str:
    source = _GENERATED_SOURCE
    if bug:
        variant = BUG_VARIANTS.get(bug)
        if variant is None:
            raise ValueError(f"Unknown UC04_INJECT_BUG={bug!r}. Known: {list(BUG_VARIANTS)}")
        if variant["find"] not in source:
            raise AssertionError("bug-injection anchor text not found in template")
        source = source.replace(variant["find"], variant["replace"], 1)
    return source


class ImplementationAI(AILayer):
    def generate(
        self, rules: list[BusinessRule], sig: IOSignature, tests: list[TestVector]
    ) -> AIResult[SourceFile]:
        ctx = {
            "rule_count": len(rules),
            "rules": [r.model_dump() for r in rules],
            "io_signature": sig.model_dump(),
            # tests are inputs only - never golden outputs (G1)
            "sample_inputs": [t.input for t in tests[:5]],
        }

        bug = os.environ.get("UC04_INJECT_BUG") or None

        def _mock():
            content = _build_source(bug)
            reasoning = (
                "Reimplemented every rule with an observable output field, as a "
                "compilable Java class run over the same pipe-delimited wire "
                "protocol as the COBOL oracle. Deliberately did not guess at "
                "unobserved oracle behaviour (no rule describes a cap), and made "
                "an explicit, documented choice on the rounding tie-break R-009 "
                "leaves open."
            )
            if bug:
                reasoning += (
                    f" [DEMO ONLY: UC04_INJECT_BUG={bug!r} is active - "
                    f"{BUG_VARIANTS[bug]['description']}]"
                )
            return {
                "value": {
                    "path": "generated/GeneratedIntcalc.java",
                    "content": content,
                    "citations": _CITATIONS,
                },
                "confidence": 0.85,
                "citations": [
                    {"source": "data/rules/validated_rules.yaml", "ref": rid}
                    for rid in sorted({rid for rids in _CITATIONS.values() for rid in rids})
                ],
                "abstained": False,
                "reasoning": reasoning,
            }

        ctx["_mock"] = _mock
        return self.call("implementation", ctx, SourceFile)
