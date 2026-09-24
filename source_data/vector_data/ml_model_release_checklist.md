# ML Model Release Checklist

Owner: ML Engineering, led by Jonas Weber.

## Before release

The model code is merged into GitHub with at least one review. The training run is reproducible from a tagged commit. Evaluation metrics are compared with the current production model on the same holdout set.

## Quality gates

A new Beacon model must not reduce click-through on the holdout set by more than 1 percent. Latency at the 95th percentile must stay under 120 ms. Fairness metrics across user segments must be reviewed and signed off by the ML Lead.

## Rollout

Models roll out to 5 percent of traffic first, then 25 percent, then 100 percent, with 24 hours between steps. Dashboards in Grafana track quality and latency during the rollout.

## Rollback

If a quality gate fails during rollout, revert to the previous model version immediately and open an incident. The previous version is kept warm for 14 days after every release.
