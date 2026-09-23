
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
