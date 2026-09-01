# DiffWitness Private Engine — alpha activation

The Private Engine is an **optional advisory planner** for Adaptive Core. It can change which counterfactual experiments DiffWitness tries first; it cannot mint, validate, weaken, or override a public proof.

## Install and activate

Install the public DiffWitness package and the licensed private-engine artifact into the same environment, then from the target Git checkout run:

```bash
dw engine enable
dw engine status
dw doctor
```

`dw engine enable` defaults to the installed `dw-private-engine` executable. It runs the engine's versioned `--capabilities` preflight **before** activation and refuses incompatible protocol, privacy, or authority contracts.

The activation is stored under Git metadata (`git rev-parse --git-path diffwitness/engine.json`). It is local to Git plumbing rather than a tracked project file, so enabling a paid engine does not change the candidate software tree or require teams to commit a commercial setting.

To remove only the local activation:

```bash
dw engine disable
```

## Precedence

DiffWitness deliberately uses this order:

1. explicit engine CLI option for the current command;
2. committed `[engine]` project policy in `.diffwitness.toml`;
3. Git-local engine activation created by `dw engine enable`;
4. Community planner.

A machine-local paid activation therefore cannot silently override a repository's committed engine policy.

## Required vs optional

The default local activation is **required**. If the selected private engine later becomes unavailable or invalid, an Adaptive Gate fails rather than silently changing planning semantics mid-run.

For a deliberate Community fallback:

```bash
dw engine enable --no-required
```

This affects planning availability only. Public evidence execution and proof-policy evaluation remain authoritative either way.

## Trust boundary

A compatible engine must declare that it:

- accepts `engine-request-1` and returns `engine-plan-1`;
- refuses embedded source in the request;
- supports metadata-only planning;
- is advisory-only;
- does not execute the evidence/test command;
- does not write the target repository.

DiffWitness independently validates every returned plan, binds it to the exact request digest, and then runs the actual counterfactual evidence itself. A private planner can save experiments; it cannot turn a hypothesis into proof.

## Inspect before relying on it

```bash
dw engine status --json
```

This performs a fresh capability preflight and reports whether the active source is `project`, `local`, or `community`.

The commercial-alpha CI exercises this lifecycle from the **exact built public wheel** on Linux, macOS, and Windows: local activation → private plan → Adaptive Gate → public 1-minimal proof → disable → Community fallback.
