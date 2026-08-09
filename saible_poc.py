"""
Saible fraud-monitoring — proof of concept
==========================================

A lightweight demonstration of a transaction-monitoring layer for a
parallel-payment construction platform. It generates SYNTHETIC payment data
(no real data is used anywhere) and scores each payment against the fraud
typologies that actually hit construction supply chains:

  1. Mandate fraud     - payee bank details changed just before a payment run
  2. Duplicate invoice - same payee + amount seen twice in a short window
  3. Ghost subcontractor - brand-new payee, paid once, large value, no history
  4. Over-certification - payment exceeds the certified value of work done
  5. Structuring       - amount nudged just under an approval threshold

Output: a ranked alert list an analyst can action, written to alerts.csv.

Run:  python saible_poc.py
"""

import csv
import random
from collections import defaultdict
from datetime import date, timedelta

random.seed(7)  # reproducible demo

APPROVAL_THRESHOLD = 10_000  # payments >= this need extra sign-off
START = date(2026, 1, 6)

TIER1 = ["Meridian Main Contractors", "Kestrel Build Group"]
TIER2 = ["Haldane Groundworks", "Pennine M&E", "Brightwater Civils",
         "Irongate Steel", "Verda Landscaping", "Coppergate Electrical"]
TIER3 = ["Ashcroft Plant Hire", "Delta Scaffolding", "Rowan Joinery",
         "Marsh Plumbing", "Quill Surveying", "Basalt Concrete"]


def sortcode():
    return f"{random.randint(10,99)}-{random.randint(10,99)}-{random.randint(10,99)}"


def account():
    return str(random.randint(10_000_000, 99_999_999))


def build_supplier_registry():
    """Each supplier has a bank account on file and a date first added."""
    reg = {}
    all_suppliers = ([(n, 1) for n in TIER1] +
                     [(n, 2) for n in TIER2] +
                     [(n, 3) for n in TIER3])
    for name, tier in all_suppliers:
        reg[name] = {
            "tier": tier,
            "bank": (sortcode(), account()),
            "added": START - timedelta(days=random.randint(90, 400)),
        }
    return reg


def generate_transactions(reg):
    """Create a stream of legitimate payments, then inject known frauds."""
    txns = []
    tid = 1000

    def new(**kw):
        nonlocal tid
        tid += 1
        base = {
            "txn_id": f"TXN-{tid}",
            "date": START + timedelta(days=random.randint(0, 60)),
            "project": random.choice(["P-Northgate", "P-Riverside", "P-Depot"]),
            "payer": random.choice(TIER1),
            "bank_change_days": None,   # days since payee bank changed (None = unchanged)
            "is_seed_fraud": False,     # ground-truth label, for the demo only
        }
        base.update(kw)
        return base

    # --- legitimate payments -------------------------------------------------
    for _ in range(180):
        payee = random.choice(list(reg))
        info = reg[payee]
        certified = random.randint(2_000, 40_000)
        txns.append(new(
            payee=payee, tier=info["tier"], bank=info["bank"],
            invoice_amount=certified,               # paid == certified
            certified_value=certified,
            payee_added=info["added"],
        ))

    # --- 1. mandate fraud: bank details changed 2 days before payment --------
    for payee in ["Pennine M&E", "Brightwater Civils"]:
        info = reg[payee]
        amt = random.randint(15_000, 28_000)
        txns.append(new(
            payee=payee, tier=info["tier"],
            bank=(sortcode(), account()),           # NEW, unrecognised account
            bank_change_days=2,
            invoice_amount=amt, certified_value=amt,
            payee_added=info["added"], is_seed_fraud=True,
        ))

    # --- 2. duplicate invoice: same payee + amount, days apart --------------
    dup_payee, dup_amt = "Irongate Steel", 12_450
    info = reg[dup_payee]
    for offset in (10, 13):
        txns.append(new(
            payee=dup_payee, tier=info["tier"], bank=info["bank"],
            date=START + timedelta(days=offset),
            invoice_amount=dup_amt, certified_value=dup_amt,
            payee_added=info["added"], is_seed_fraud=True,
        ))

    # --- 3. ghost subcontractor: brand-new payee, one big payment -----------
    ghost = "Northface Contracting Ltd"
    reg[ghost] = {"tier": 3, "bank": (sortcode(), account()),
                  "added": START + timedelta(days=25)}
    txns.append(new(
        payee=ghost, tier=3, bank=reg[ghost]["bank"],
        date=START + timedelta(days=27),
        invoice_amount=31_000, certified_value=31_000,
        payee_added=reg[ghost]["added"], is_seed_fraud=True,
    ))

    # --- 4. over-certification: paid well above certified value -------------
    oc_payee = "Haldane Groundworks"
    info = reg[oc_payee]
    txns.append(new(
        payee=oc_payee, tier=info["tier"], bank=info["bank"],
        invoice_amount=27_500, certified_value=18_000,   # +53% over cert
        payee_added=info["added"], is_seed_fraud=True,
    ))

    # --- 5. structuring: amount parked just under the sign-off threshold ----
    for payee in ["Coppergate Electrical", "Verda Landscaping"]:
        info = reg[payee]
        amt = APPROVAL_THRESHOLD - random.randint(40, 120)   # e.g. 9,930
        txns.append(new(
            payee=payee, tier=info["tier"], bank=info["bank"],
            invoice_amount=amt, certified_value=amt,
            payee_added=info["added"], is_seed_fraud=True,
        ))

    return txns


# ---------------------------------------------------------------------------
# Detection rules — each returns (triggered: bool, reason: str)
# ---------------------------------------------------------------------------

RULE_WEIGHTS = {
    "mandate_fraud": 45,
    "ghost_subcontractor": 30,
    "over_certification": 25,
    "duplicate_invoice": 25,
    "structuring": 15,
}


def detect(txns):
    # pre-compute cross-transaction context
    pay_count = defaultdict(int)
    for t in txns:
        pay_count[t["payee"]] += 1

    dup_index = defaultdict(list)  # (payee, amount) -> list of dates
    for t in txns:
        dup_index[(t["payee"], t["invoice_amount"])].append(t["date"])

    alerts = []
    for t in txns:
        reasons, score = [], 0

        # 1. mandate fraud
        if t["bank_change_days"] is not None and t["bank_change_days"] <= 7:
            reasons.append(
                f"bank details changed {t['bank_change_days']}d before payment")
            score += RULE_WEIGHTS["mandate_fraud"]

        # 2. duplicate invoice (same payee+amount within 14 days)
        dates = sorted(dup_index[(t["payee"], t["invoice_amount"])])
        if len(dates) > 1:
            gap = (dates[-1] - dates[0]).days
            if 0 < gap <= 14:
                reasons.append(
                    f"duplicate amount \u00a3{t['invoice_amount']:,} within {gap}d")
                score += RULE_WEIGHTS["duplicate_invoice"]

        # 3. ghost subcontractor
        age_days = (t["date"] - t["payee_added"]).days
        if age_days <= 30 and pay_count[t["payee"]] == 1 and t["invoice_amount"] >= 20_000:
            reasons.append(
                f"new payee (added {age_days}d ago), single large payment")
            score += RULE_WEIGHTS["ghost_subcontractor"]

        # 4. over-certification
        if t["invoice_amount"] > t["certified_value"]:
            over = (t["invoice_amount"] / t["certified_value"] - 1) * 100
            reasons.append(f"paid {over:.0f}% over certified value")
            score += RULE_WEIGHTS["over_certification"]

        # 5. structuring
        if 0 < APPROVAL_THRESHOLD - t["invoice_amount"] <= 150:
            reasons.append(
                f"\u00a3{t['invoice_amount']:,} sits just under \u00a3{APPROVAL_THRESHOLD:,} threshold")
            score += RULE_WEIGHTS["structuring"]

        if reasons:
            alerts.append({
                "txn_id": t["txn_id"],
                "date": t["date"].isoformat(),
                "project": t["project"],
                "payee": t["payee"],
                "tier": t["tier"],
                "amount": t["invoice_amount"],
                "risk_score": min(score, 100),
                "reasons": "; ".join(reasons),
                "seeded_fraud": t["is_seed_fraud"],
            })

    alerts.sort(key=lambda a: a["risk_score"], reverse=True)
    return alerts


def main():
    reg = build_supplier_registry()
    txns = generate_transactions(reg)
    alerts = detect(txns)

    total_fraud = sum(1 for t in txns if t["is_seed_fraud"])
    caught = sum(1 for a in alerts if a["seeded_fraud"])

    print(f"\n  Saible fraud-monitoring \u2014 proof of concept (synthetic data)")
    print(f"  {'-'*60}")
    print(f"  Payments screened : {len(txns)}")
    print(f"  Alerts raised     : {len(alerts)}")
    print(f"  Seeded frauds      : {total_fraud}  |  caught: {caught}/{total_fraud}")
    print(f"  {'-'*60}\n")
    print(f"  {'RISK':>4}  {'TXN':<9} {'PAYEE':<28} {'AMOUNT':>9}  WHY")
    for a in alerts[:12]:
        print(f"  {a['risk_score']:>4}  {a['txn_id']:<9} {a['payee'][:27]:<28} "
              f"\u00a3{a['amount']:>7,}  {a['reasons']}")

    with open("alerts.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(alerts[0].keys()))
        w.writeheader()
        w.writerows(alerts)
    print(f"\n  Full alert list written to alerts.csv\n")


if __name__ == "__main__":
    main()
