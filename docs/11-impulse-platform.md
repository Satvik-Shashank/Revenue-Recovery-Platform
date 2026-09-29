# Impulse revenue platform: architecture and honest limits

The chargeback engine (docs 01-10) is now the first module of a wider platform. One **Decision Kernel** decides
for every module; everything else feeds it or records its outcomes.

```
webhooks / CSV -> adapters -> canonical schema -> identity -> Customer Passport
                                                         |
      Payment Recovery | Clawback Defense | Retention Rescue | Billing (roadmap)
                                                         |
             Decision Kernel: EV = P(success) x value - cost - risk (+ learning value)
                 guardrails - budgets - autonomy (auto / approve / recommend)
                                                         |
                 Action layer -> Approval inbox -> Outcome Ledger (hash-chained)
```

## Where things live (`src/impulse/`)

| Concern | Module |
|---|---|
| Canonical entities, decline taxonomy | `schema.py`, `declines.py` |
| Razorpay / Stripe / custom adapters, signatures, idempotency, dead-letter queue, replay | `adapters.py`, `ingest.py` |
| Deterministic identity merges, suggested (human) merges, unmerge audit | `identity.py` |
| Revenue Passport (LTV, trust, churn, payment health, exposure, case fusion) | `passport.py` |
| Kernel, guardrails, policy-as-config | `kernel.py`, `policy.py` |
| Payment Recovery (retry bandit, journeys, pre-dunning, routing advice, recurring-debit compliance) | `payments.py` |
| Clawback: chargebacks on top of the existing tested pipeline, refund abuse, COD/RTO | `clawback.py`, `refunds.py`, `rto.py` |
| Retention (churn v1, save ladder, persuadability, win-back) | `retention.py` |
| Billing assurance and collections (demo on planted errors) | `billing.py` |
| Action layer with approved templates | `actions.py` |
| Outcome ledger, holdout attribution, fee | `ledger.py` |
| Replay Lab (simulated world with hidden ground truth) | `sim.py` |
| Leak Audit (column auto-mapping, report) | `audit.py` |
| Optional Claude language layer (never decides) | `narrative.py` |
| Orchestrator, demo world, HTTP routes | `engine.py`, `demo.py`, `routes.py` |

UI: one app in `public/index.html`. The navbar has a tab per pillar (Payment Recovery, Clawback Defense, Retention Rescue, Billing & Collections) plus Home and Platform. The original chargeback screens live under Clawback Defense. Platform screens are `public/platform.js` + `platform.css`; customer-facing pages are `public/hosted.html`. API: `/api/impulse/*`.

## Run it

```
python -m uvicorn api.index:app --port 8000     # open http://localhost:8000/
python -m src.impulse.sim 1200                  # regenerate results/replay_lab.json
python -m pytest tests                          # 121 tests
```

`IMPULSE_EMPTY=1` starts with an empty workspace instead of the seeded demo merchant.
Set `ANTHROPIC_API_KEY` (and install `anthropic`) to let Claude polish evidence narratives and messages.

## Honest limits

- **State is in memory.** Each warm instance seeds the same deterministic demo world. Production needs the ledger,
  bandit state, passports and approvals in Postgres (`DATABASE_URL` is already supported by the chargeback store).
- **Synthetic data.** The demo merchant and the Replay Lab encode our assumptions. Outcomes for retention, refunds and
  RTO are sampled from the model's own probabilities and are labelled "simulated". Post real outcomes to
  `/api/impulse/cases/{id}/resolve` to replace them; a real success webhook already closes a recovery case with a real outcome.
- **Replay Lab result.** Against the merchant's original retry logic Impulse gains ~27 points of recovery (95% interval
  ~25 to 30). Against a well-built static playbook the recovery rate is roughly level: the edge is fewer retries and lower
  churn. The bandit adds ~2 points of recovery over its own frozen priors but can cost some churn. All shown in the UI.
- **Economic assumptions** (dispute fee, chargeback-ratio damage, cost to fight) are Settings, not industry facts.
  With them, refunding early beats fighting only on small tickets with weak evidence.
- **Compliance constants** (24h pre-debit notice, Rs 15,000 additional-authentication limit, MSME 45-day rule) must be
  verified against current RBI/MSME rules before production use.
- **Message delivery is simulated**: nothing is actually sent to customers.
- The chargeback accuracy figures still come from synthetic data (see PROJECT_STATUS.md).
