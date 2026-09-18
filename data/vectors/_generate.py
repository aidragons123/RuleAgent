"""
_generate.py - one-time generator for seed_vectors.jsonl and
heldback_vectors.jsonl. Kept in the repo for transparency: this is how
the shipped vector files were built, from the pathologies listed in
the use-case brief. It is NOT part of the runtime pipeline and is
never imported by core/, ai/, or tests/.

Each vector holds INPUT fields only - no expected output. Expected
values are always computed live by core/cobol_runner.py against the
oracle, per guardrail G1 (never derive an expected value from
anywhere else).
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
random.seed(20260918)


def overpunch(digits7: str, sign: str, last_digit: int) -> str:
    """8-char field: 7 digit characters (the 7th is irrelevant - the
    oracle overwrites it with the decoded digit) + 1 overpunch char
    that encodes both sign and final digit."""
    pos = "{ABCDEFGHI"
    neg = "}JKLMNOPQR"
    table = pos if sign == "+" else neg
    return digits7[:7] + table[last_digit]


def mk_input(account_id, balance, adj_digits7, adj_sign, adj_last_digit,
             yy, mm="06", dd="15"):
    return {
        "account_id": f"{account_id:06d}",
        "balance": f"{balance:011.2f}",
        "adjustment_overpunch": overpunch(f"{adj_digits7:07d}", adj_sign, adj_last_digit),
        "member_since_yy": f"{yy:02d}",
        "member_since_mm": mm,
        "member_since_dd": dd,
    }


def vec(vid, rule_ids, note, **kw):
    return {"id": vid, "rule_ids": rule_ids, "note": note, "input": mk_input(**kw)}


# ---------------------------------------------------------------- seed
# Deliberately easy: mid-tier balances, safely below the undocumented
# cap crossover (~16,666.67 at the tier-3 rate), away from every tier
# boundary and every half-cent rounding tie. A naive implementation
# should pass all 30 of these - the pathologies only show up in the
# held-back set.
seed = []
n = 0
for balance in [50, 250, 750, 1500, 3000, 7000, 11500, 13200, 15900]:
    n += 1
    # Tag only R-004/R-014 (the general "interest = balance*rate for its
    # tier" rules) plus the ONE tier-rate rule this specific balance
    # actually exercises - never all three tier-rate rules on a single
    # vector, since a given balance can only be in one tier.
    tier_rule = "R-005" if balance <= 1000 else ("R-006" if balance <= 10000 else "R-007")
    seed.append(vec(
        f"SEED-{n:03d}", ["R-004", "R-014", tier_rule],
        "Easy happy-path balance, mid-tier, no boundary, no pathology.",
        account_id=100000 + n, balance=balance,
        adj_digits7=1234500 + n, adj_sign="+", adj_last_digit=random.randint(1, 8),
        yy=random.randint(51, 90),
    ))
while len(seed) < 30:
    n += 1
    balance = round(random.uniform(20, 15800), 2)
    seed.append(vec(
        f"SEED-{n:03d}", ["R-004", "R-014"],
        "Easy random balance away from all tier and rounding boundaries.",
        account_id=100000 + n, balance=balance,
        adj_digits7=random.randint(0, 9999990), adj_sign=random.choice("+-"),
        adj_last_digit=random.randint(1, 9),
        yy=random.randint(55, 95),
    ))
seed = seed[:30]

# ------------------------------------------------------------ heldback
held = []
n = 0


def add(rule_ids, note, **kw):
    global n
    n += 1
    held.append(vec(f"HELD-{n:03d}", rule_ids, note, **kw))


# Pathology 1: COMP-3 half-cent rounding ties (raw interest lands on
# an exact x.xx5). balance * rate must equal exactly N.NN5.
for bal, tag in [(832.50, "tier1"), (837.50, "tier1"), (1250.25, "tier2"),
                 (1750.25, "tier2"), (12500.25, "tier3-below-cap"),
                 (16675.00, "tier3-below-cap"), (91.50, "tier1"), (562.50, "tier1")]:
    add(["R-009"], f"Half-cent rounding tie ({tag}): balance*rate lands on an exact half cent.",
        account_id=200000 + n, balance=bal,
        adj_digits7=1234560 + n, adj_sign="+", adj_last_digit=5,
        yy=random.randint(51, 95))

# Pathology 2: signed overpunch edge cases - both tables, digit 0 and 9,
# zero-magnitude adjustment (R-012).
for sign, digit in [("+", 0), ("+", 9), ("-", 0), ("-", 9), ("+", 5), ("-", 5)]:
    add(["R-011", "R-012"],
        f"Overpunch edge case: sign={sign} last_digit={digit}.",
        account_id=210000 + n, balance=round(random.uniform(100, 9000), 2),
        adj_digits7=0, adj_sign=sign, adj_last_digit=digit,
        yy=random.randint(51, 95))
# zero-magnitude, both signs, to test R-012 (zero reported positive)
for sign in ["+", "-"]:
    add(["R-012"], "Zero-magnitude adjustment must be reported positive regardless of encoded sign.",
        account_id=210500 + n, balance=round(random.uniform(100, 9000), 2),
        adj_digits7=0, adj_sign=sign, adj_last_digit=0,
        yy=random.randint(51, 95))

# Pathology 3: two-digit year pivot boundary (49/50 and 99/00).
for yy in [49, 50, 99, 0, 1, 48, 51]:
    add(["R-013"], f"Year-pivot boundary: yy={yy:02d}.",
        account_id=220000 + n, balance=round(random.uniform(100, 9000), 2),
        adj_digits7=1230000 + n, adj_sign="+", adj_last_digit=3, yy=yy)

# Pathology 4: tier boundary exact values and near misses (R-008/R-016/R-017).
for bal in [999.99, 1000.00, 1000.01, 9999.99, 10000.00, 10000.01, 0.00, 0.01]:
    add(["R-008", "R-016", "R-017", "R-003"], f"Tier boundary probe at balance={bal:.2f}.",
        account_id=230000 + n, balance=bal,
        adj_digits7=1111110 + n, adj_sign="+", adj_last_digit=1,
        yy=random.randint(51, 95))

# Pathology 5: tier-3 balances that trigger the undocumented cap, and
# ones just below the cap threshold (interest cap is 500.00 => balance
# ~16666.67 at 3% is the crossover).
for bal in [16600.00, 16666.66, 16666.67, 16700.00, 20000.00, 50000.00, 100000.00]:
    add(["R-007", "R-014"],
        f"Tier-3 high balance probe at balance={bal:.2f} (near/over the undocumented cap).",
        account_id=240000 + n, balance=bal,
        adj_digits7=2222220 + n, adj_sign="-", adj_last_digit=2,
        yy=random.randint(51, 95))

# Pathology 6: R-023/R-024 paired-but-uncoverable-together vectors -
# one on each side of year 2000, explicitly tagged as a pair.
for yy, tag in [(5, "post-2000"), (95, "pre-2000")]:
    add(["R-023", "R-024"],
        f"Legacy/standard tenure probe ({tag}) - paired rule, only one side observable per vector.",
        account_id=250000 + n, balance=round(random.uniform(500, 5000), 2),
        adj_digits7=3333330 + n, adj_sign="+", adj_last_digit=7, yy=yy)

# Fill remaining to 200 with a broad random spread across all fields,
# biased toward re-hitting the boundaries above with fresh account ids.
boundary_balances = [999.99, 1000.00, 1000.01, 9999.99, 10000.00, 10000.01,
                      832.50, 1250.25, 16666.67]
while len(held) < 200:
    strat = random.choice(["boundary", "random", "overpunch", "year"])
    if strat == "boundary":
        bal = random.choice(boundary_balances)
    else:
        bal = round(random.uniform(0, 120000), 2)
    add(["R-004", "R-014"], "Broad-spread fill vector across the input space.",
        account_id=260000 + n, balance=bal,
        adj_digits7=random.randint(0, 9999990), adj_sign=random.choice("+-"),
        adj_last_digit=random.randint(0, 9),
        yy=random.randint(0, 99))

held = held[:200]

(HERE / "seed_vectors.jsonl").write_text(
    "\n".join(json.dumps(v) for v in seed) + "\n")
(HERE / "heldback_vectors.jsonl").write_text(
    "\n".join(json.dumps(v) for v in held) + "\n")

print(f"wrote {len(seed)} seed vectors, {len(held)} heldback vectors")
