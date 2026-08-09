# Fraud monitoring for construction payments (proof of concept)

This is a small proof of concept I put together to show what a fraud-monitoring
layer could look like on top of a parallel-payment platform like Saible. It runs
on completely synthetic data. Nothing real is used, referenced, or needed to run it.

I kept it deliberately small. The point isn't the amount of code, it's to show
the fraud patterns that actually show up in construction supply chains, and how
you'd surface them as a ranked queue an analyst can work through.

## What it looks for

I focused on the five patterns that cause the most damage in construction payments:

| Pattern | What gets flagged | Why it matters |
|---|---|---|
| Mandate fraud | A payee's bank details change just before a payment goes out | This is the classic push-payment scam. Money lands in a fraudster's account instead of the real supplier's. |
| Duplicate invoice | The same payee and amount appears twice in a short window | Double billing, which is easy to miss across different tiers of the chain. |
| Ghost subcontractor | A brand new payee gets one large payment and is never seen again | Phantom firms set up to pull a single payment out. |
| Over-certification | A payment comes in higher than the certified value of the work | Inflated valuations slipping through. |
| Structuring | An amount sits just under an approval threshold | Someone keeping payments under the level that would trigger extra sign-off. |

Every payment gets a risk score, and the output is sorted highest risk first.

You'll notice a couple of the structuring alerts are actually legitimate payments
that just happen to fall under the threshold. That's on purpose. Rules like this
are meant to be a bit sensitive, so what you get is a prioritised list for a human
to review, not something that blocks payments automatically. Tuning that noise
down is exactly what the next phase is for.

## Example run

```
Payments screened : 188
Alerts raised     : 10
Seeded frauds     : 8  |  caught: 8/8

RISK  TXN       PAYEE                        AMOUNT   WHY
  45  TXN-1181  Pennine M&E                  £15,906  bank details changed 2d before payment
  30  TXN-1185  Northface Contracting Ltd    £31,000  new payee (added 2d ago), single large payment
  25  TXN-1183  Irongate Steel               £12,450  duplicate amount within 3d
  25  TXN-1186  Haldane Groundworks          £27,500  paid 53% over certified value
  15  TXN-1187  Coppergate Electrical         £9,901  sits just under £10,000 threshold
```

## Running it

```bash
python saible_poc.py
```

No packages to install. It's Python 3.9 or newer, standard library only. It prints
the alert list and writes the full version to alerts.csv.

## What it's built on

Right now it's just Python and the standard library, so it runs anywhere with
nothing to set up. The full version would sit on PostgreSQL with a pandas ELT
pipeline for ingestion (the same setup as my earlier fraud platform), scikit-learn
for scoring once there's data to train on, and a simple dashboard for the review
queue.

## Where I'd take it next

I built this rules-first on purpose. You can't train a model until you've caught
some fraud to learn from, and the rules are what start catching it. Rules also
give you a plain-English reason for every flag, which matters a lot for AML work,
since a suspicious activity report needs a reason a person can read, not "the
model said so."

So the order I'd build it in:

1. Rules engine. That's this POC. Explainable flags, scored and ranked.
2. Data pipeline. Move payment events into PostgreSQL and build proper features
   (payee history, how fast payments are moving, tier relationships, bank changes).
3. Machine learning. Once analysts have marked which alerts were real, train a
   model (scikit-learn or XGBoost) to score payments alongside the rules. This is
   where you cut the false positives, like those structuring flags above, by
   letting the model learn which ones are harmless.
4. Network analysis. Look across the whole supply chain for collusion and circular
   payments, plus unsupervised methods to catch patterns the rules don't cover.
5. Case management. Proper case files ready for reporting, with analyst decisions
   feeding back into the model, and a view built for the MLRO.

Put together by a former American Express fraud analyst (3.5 years).
