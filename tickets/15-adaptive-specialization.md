# Ticket 15: Learn task and model specialization

## Stage

Vision

## Goal

Discover model strengths from verified outcomes instead of relying on fixed capability labels.

## Scope

- Cluster tasks by observable features and execution history.
- Estimate model performance by task cluster, language, repository shape, and verifier type.
- Handle sparse evidence and prevent small cohorts from dominating policy decisions.
- Compare learned specialization with static capability tags.
- Feed validated specialization features into offline policy evaluation.

## Acceptance criteria

- Specialization reports show sample counts and uncertainty.
- Sparse clusters fall back to broader evidence.
- The policy does not select a model from an under-supported estimate without a safe fallback.
- Learned specialization improves or matches the fixed-tag baseline on held-out tasks.

## Validation

Run synthetic cohort tests for sparse data, noisy outcomes, and distribution shift.
