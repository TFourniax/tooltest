# Advisory engine integration

DiffWitness Community owns every evidence execution and every causal acceptance decision. An optional external engine may only advise the Adaptive Core planner: it can order mutation ids and propose partitions, but the public runner independently executes the selected counterfactuals before any proof claim is emitted.

## Configure an engine

```toml
[engine]
command = ["dw-private-engine"]
timeout = 2
required = true
```

`required = true` is the recommended setting when the private edition is part of a paid/managed workflow: a missing, incompatible or malformed engine then fails closed instead of silently falling back to the Community planner.

For a non-blocking evaluation, use `required = false`. Invalid advisory output is ignored and the Community planner remains authoritative.

## Preflight before the first Gate

```bash
dw doctor
```

When an engine is configured, Doctor invokes only:

```text
<engine command> --capabilities
```

It does **not** execute the repository test command and does not send source code to the engine during this preflight.

A compatible engine advertises the versioned `engine-capabilities-1` contract. Doctor verifies:

- `engine-request-1` input compatibility;
- `engine-plan-1` output compatibility;
- bounded request and mutation capacity;
- metadata-only planning support;
- refusal of embedded source content;
- advisory-only authority;
- no evidence-command execution authority;
- no target-repository write authority.

Capabilities output is bounded to 64 KiB and the preflight itself is time-bounded. Duplicate JSON object keys, non-standard JSON values, protocol drift and authority drift fail the preflight.

Example healthy output:

```text
Advisory:   compatible - diffwitness-private 0.1.0a1 (engine-request-1 -> engine-plan-1)
Boundary:   advisory-only; no evidence execution; no repository writes; embedded source refused
```

## Runtime trust boundary

During an Adaptive Gate, Community creates a content-addressed request bound to:

- repository lineage fingerprint;
- exact base and candidate Git trees;
- exact mutation metadata;
- proof budget and policy;
- a one-way digest of the evidence command;
- changed-test file paths;
- explicit local-read privacy permission.

No test command text or patch body is embedded in the request. Engine responses are accepted only when they are bound to the exact request and cover every mutation exactly once. JSON parsing is intentionally strict: duplicate members and `NaN`/`Infinity` are rejected.

Even a valid engine plan is **not proof**. Community executes the real Git counterfactuals and records the resulting causal certificate.

## Troubleshooting

If Doctor reports `Advisory: INVALID`, fix the engine before relying on the private planner. For a required engine, `dw gate` should remain fail-closed. For an optional engine, Gate can degrade to Community, but Doctor still returns a failing preflight so a broken paid installation is not mistaken for a healthy one.
