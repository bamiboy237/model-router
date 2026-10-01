# Stateful model router

Route bounded coding subtasks to the model most likely to complete them well. The router optimizes verified task success first, then cost, latency, context transfer, cache affinity, and expected rework.

The project does not route a full user request to one model. A stateful orchestrator turns a goal into verifiable subtasks. The router selects a worker, a context packet, or local execution for each subtask.

## Problem

An API gateway cannot infer the true difficulty of a request from its latest prompt alone. Coding work gains important signals during execution:

- the relevant files and their size;
- the task type and required tools;
- whether the task has an automated verifier;
- failures, retries, and prior task results;
- model reliability for comparable work; and
- context, cache, cost, and latency constraints.

The project tests whether task-level, state-aware routing can match a strong-model baseline at lower total cost.

## Design

```text
User goal
  │
  ▼
Orchestrator ──► Task graph ──► Context builder ──► Router
      ▲                                             │
      │                                             ├──► Local execution
      │                                             └──► Worker model
      │
      └──────── Verification, state, and execution trace
```

The runtime stores long-lived state outside worker prompts. The context builder sends each worker the smallest packet that supports its task. The verifier turns worker output into evidence. The trace store feeds evaluation and later routing decisions.

## Project stages

The tickets cover the full system. Build them in order unless an evaluation result changes the plan.

### Beginning: establish evidence (`00` through `03b`)

Build the deterministic path before training a router.

1. Define `TaskSpec`, `ContextPacket`, `TaskResult`, and `ExecutionTrace`.
2. Add adapters for three worker models.
3. Record tokens, cost, latency, outcome, and verifier output for every run.
4. Add a rule-based router with explicit capability priors.
5. Create benchmark tasks for exploration, implementation, tests, debugging, refactoring, and architecture.
6. Strip `~/Desktop/simulate` to its trial-lab core (ticket `03a`), then build the lab that runs those tasks and writes trial records (ticket `03b`).

The first router uses configuration, not machine learning:

```yaml
models:
  exploration_model:
    strengths: [repository_exploration, summarization]
  coding_model:
    strengths: [implementation, tests, refactoring]
  reasoning_model:
    strengths: [architecture, ambiguous_debugging]
```

These are hypotheses. Evaluation data must be able to confirm or replace them.

### MVP: prove task-level routing (`04` through `05`)

The MVP is complete when it can:

1. Accept a coding goal and create bounded subtasks.
2. Send each subtask a minimal context packet.
3. Select a worker with the rule-based router.
4. Verify results with tests, type checks, or a task-specific checker.
5. Escalate failed or uncertain tasks to a stronger worker.
6. Save an execution trace with cost, latency, model choice, and outcome.
7. Compare the router with always-cheapest and always-strongest baselines.

The MVP success criterion is comparable verified task success with lower end-to-end spend than the always-strongest baseline.

### Post-MVP: learn and operate the router (`06` through `12`)

After the MVP, add the learned decision loop:

1. Run eligible models against the same task packets.
2. Store outcomes for every `(task, model)` pair.
3. Train predictors for success, quality, latency, and escalation risk.
4. Keep cost as a measured or price-table input.
5. Use a policy layer to optimize a configurable utility function.
6. Add task history, task clusters, context budgeting, and cache affinity.
7. Compare stateless and stateful policies on held-out tasks.
8. Add replay, drift checks, model catalog updates, and safe policy releases.

Train an outcome predictor, not a direct model classifier:

```text
(task features, model metadata, session state)
  → success probability, quality, latency, escalation risk
```

The policy layer converts predictions into a choice. This lets the product change its cost, speed, or quality preference without retraining the predictor.

### Vision: adaptive coding execution (`13` through `16`)

The mature system is a cache-aware inference scheduler and coding-task control plane:

- learns model specialization from verified outcomes;
- uses session, task-cluster, repository, and language affinity;
- selects a model, a context packet, or `DO_LOCALLY`;
- runs independent subtasks in parallel;
- preserves a durable task graph across retries and sessions;
- escalates based on failed verification, disagreement, and risk;
- supports shadow, canary, rollback, and policy versioning;
- detects distribution shift and model-quality regressions;
- improves from production traces through offline evaluation and controlled online experiments; and
- exposes decisions, evidence, spend, and quality through an operator API.

The project integrates with existing model gateways and provider APIs. It does not become a provider proxy.

## Training data and policy

For each benchmark task, run eligible models against the same task packet. Store an outcome for every `(task, model)` pair:

```json
{
  "task_features": {
    "task_type": "implementation",
    "context_tokens": 4200,
    "files": 3,
    "prior_failures": 0,
    "verifiability": 0.95
  },
  "model_id": "coding_model",
  "outcome": {
    "success": true,
    "quality": 0.92,
    "cost_usd": 0.04,
    "latency_ms": 3100,
    "escalated": false
  }
}
```

The policy can choose a model with a utility function such as:

```text
expected_quality
  - cost_weight × expected_cost
  - latency_weight × expected_latency
  - failure_weight × escalation_risk
  - context_weight × transfer_cost
```

Keep policy weights separate from the predictor. Record the policy version in every decision receipt.

## Evaluation

Measure the router against fixed baselines:

- always strongest;
- always cheapest;
- lowest-latency eligible model;
- rule-based routing; and
- learned routing.

Track verified success, quality, total cost, p50 and p95 latency, escalation rate, context tokens, cache-hit rate, and regret against the best observed eligible model.

## Project documents

- [`AGENTS.md`](AGENTS.md): instructions for agents working in this project.
- [`tickets/`](tickets/): ordered implementation tickets from foundation to vision.
