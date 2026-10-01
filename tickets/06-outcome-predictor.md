# Ticket 06: Train the learned outcome predictor

## Stage

Post-MVP

## Goal

Predict a model's expected outcome for a task from benchmark data.

## Scope

- Build features from task metadata, context size, verification type, model metadata, and prior failures.
- Train predictors for success probability, quality, latency, and escalation risk.
- Keep cost as a measured or price-table input.
- Split training and held-out tasks by task identity.
- Report calibration, ranking quality, and missing-feature behavior.

## Acceptance criteria

- Training and evaluation are reproducible from a versioned dataset.
- The predictor emits estimates for every eligible model.
- The evaluation reports calibration and regret against the best observed model.
- The predictor does not use post-outcome fields as input features.

## Validation

Run a deterministic training job and a held-out evaluation report.
