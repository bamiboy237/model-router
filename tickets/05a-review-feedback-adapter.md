# Ticket 05a: Collect review feedback from the orchestrator and editor

## Stage

MVP

## Goal

Let the orchestrator and the user report how a delegated result turned out, so the router can learn from tasks that commands cannot check.

## Scope

- Expose `report_outcome` to the orchestrator as a tool, for example through MCP.
- Add an editor hook, such as a VS Code extension, that records accept, reject, and partial keep on a delegated diff.
- Have the orchestrator turn user comments into structured events. Raw comments stay out of traces.
- Let the orchestrator answer a rejection with an explicit choice: retry, escalate, clarify, or stop.
- Persist feedback events next to traces.

## Acceptance criteria

- A review in the editor produces one event tied to the attempt and its patch hash.
- A rejection starts no attempt unless the orchestrator asks for one.
- Feedback that arrives after the run is attached without changing the trace.
- No raw comment text reaches stored events or traces.

## Validation

Run `ruff`, `mypy --strict`, and the schema check. Then run a throwaway script that drives the tool and the hook with scripted reviews.

## Notes

- Ticket `03` defines `FeedbackEvent`, `report_outcome()`, and `tally()`.
- Choose a versioned observation window for keep-or-revert signals before using them as labels.
- Ticket `06` decides how feedback labels enter training.
