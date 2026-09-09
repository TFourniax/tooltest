# LANG-001 / HT-003: deterministic presentation language

Baseline resolved from GitHub before work: `46f6238e27dd0617db09da2098e4e6bbbd84a4c8`, tree `d0e1a77b988cf96a83f80f0e15dcc262fe534732`. PR #57 is merged; exact-main workflows 34355327978 / 34355327947 / 34355327936 / 34355327969 are SUCCESS. This branch does not reopen HT013/HT014.

## Reproduction before implementation

`qualification/lang001-before.json` captures public invocations in a fresh unborn fixture with LANG/LC_ALL/LANGUAGE set to French. Default help is English, status Guided is French with English actions, doctor mixes English Proof state with French instructions, setup mixes French labels with English agent fallback, and Protect Guided is French. Neither `dw language` nor an explicit language option exists. No preference file is created. The actual cause is language hardcoded by view, not demonstrated locale inference. View selection currently uses DIFFWITNESS_VIEW then repository-local ui-preferences.json then Guided. No product language configuration exists; code-language detection and optional AI soul instructions are separate concepts.

## Contract decided before implementation

Keep Guided/Technical selection independent. Reuse the existing repository-local UI preference file and schema; add an optional `language` field. `dw language en|fr` explicitly saves it; `dw language` reports the effective language. Add a root invocation option `dw --language en|fr <command>`; it applies only to that invocation and must precede the command. Precedence: explicit root option, saved project preference, English. Never consult OS locale, LANG, LC_ALL, LANGUAGE or a locale-derived persistent default. Unsupported explicit values fail with an actionable error. Reading does not create a preference file. Saving either view or language preserves the other preference.

Localization is explicit at human rendering boundaries. No stdout search/replace, no translation of user paths/commands/text, JSON dictionaries, reason codes, status enums, certificates or persisted evidence. Native ide-hook execution remains in the canonical English context regardless of UI preference. No language argument is added to generated hooks; no hook installation/trust/runtime changes. Child-agent arguments after `--` are untouched. Existing ordinary core diagnostic details and provider/tool output remain canonical verbatim where they represent evidence.

Audit includes status, doctor, setup, native readiness text, Protect UI (presentation only), explain, context, public help, Proof/Guard/Gate/Debt/Continuity terminal summaries and errors. UI changes in protect_ui/readiness/setup are a concrete presentation dependency, not permission to modify protected runtime state builders. Guided/Technical continue reading the same facts. Tests must prove locale independence, explicit/persistent precedence, cross-mode and JSON invariance, no implicit persistence, and unchanged protected hook/index/evidence bytes.

No merge before targeted HUMAN qualification and owner instruction. Preserve the old failed fixture; human language checks use a fresh disposable project and do not replay unrelated Protect runtime qualification.

## Implementation and audit notes

The selection uses an invocation-scoped ContextVar reset even on failure. Public root dispatch reads only the existing local UI preferences. `ide-hook` and legacy `session-start`/`session-stop` explicitly retain canonical English regardless of saved/explicit UI selection; their generated payloads and commands are unchanged. Agent arguments after `--` are not interpreted as DiffWitness language options.

Human strings are selected at explicit renderer/print/help boundaries with `tr(english, french)`. This is not a stream translation layer. Status actions remain canonical in JSON and are presented from the same bounded fields. Code symbols, enum labels, commands, user-authored text, saved evidence excerpts and third-party diagnostics are kept verbatim. French presentation can therefore quote canonical English diagnostic/evidence content; it does not rewrite that content or its identity. Optional model-generated prose is user-controlled and is outside deterministic core translation.

Audit of cli/guard/gate/proof_cli/debt_cli/frontend/continuity_cli/view_mode: removing only `tr` calls (selecting their original English argument) and the language import produces an AST identical to qualified main. Their execution, decisions, data builders and persistence are unchanged. Setup installation/uninstallation/state builders, readiness projections, Protect implementation, native payload builders, Git byte transport, non-UTF8 rejection, identity and attestation/report canonicalization are unchanged. Three existing UI assertions now expect English instead of implicit French; their semantic and native journey assertions remain in place. New tests separately require explicit French.

Targeted coverage includes hostile French locale hints; no implicit preference file; saved/one-off precedence in both directions; view preservation; CLI status/doctor/setup/Protect JSON equality; rendering from unchanged shared state; native canonical context and untouched agent argv; a real executed stable-fail/stable-pass contrast rendered twice from the same evidence with identical certificate content/ID (except generated_at). Installed wheels and standalone binaries run scripts/language_acceptance.py on all three OSes alongside the existing qualified native and installation journeys.

## Local qualification

350 tests PASS, including all existing qualified native/Protect/Proof/unborn/identity regressions. ProofBench 4/4 PASS. ContinuityBench 10k PASS (hot p95 178.028 ms, limit 300 ms). Integrated Product Smoke PASS with sidecar 49c4daa04088e3ba270e9e97810dd40e48bad29b. Installed language acceptance PASS locally. Python 3.11 syntax parsing PASS. Exact candidate SHA/tree and authoritative CI/package artifact IDs are recorded in the PR qualification comment so the frozen candidate does not need a self-referential source update.
