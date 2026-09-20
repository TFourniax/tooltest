# Shared structure extraction

`dw state extract --json` consumes one UTF-8 JSON object on stdin and writes one
JSON response after complete admission. It works outside a Git repository and
does not open source paths, execute project code, persist inputs, or call a service.
The caller owns source-file admission. A source hash binds supplied bytes; it does
not establish that they belong to any Git tree or that the program is correct.

```json
{"schema_version":"structure-request-1","files":[{"path":"app.py","content_base64":"ZGVmIG9rKCk6IHBhc3MK"}]}
```

The `structure-response-1` response contains `files` in request order and `coverage`
counts for `files`, `parsed`, `unsupported` and `unparsed`. Each file is the existing
`structure-extraction-1` result: `path`, `language`, `provider`, `source_sha256`,
`module`, `parsed`, `symbols`, `imports` and `calls`. Python uses the canonical
`python-ast` provider. AST declarations/imports are OBSERVED; name-only calls remain
INFERRED. No output becomes Proof. Invalid Python has `parsed: false` and no facts.
Unsupported extensions have provider `file-only`, language `unknown`, the exact
source digest and empty facts. This explicitly does not claim multi-language
semantic coverage. No timestamps, machine paths or presentation language enter
the result.

Requests require exact fields, unique unambiguous relative POSIX paths and canonical
base64. Limits: 64 files, 1 MiB per file, 4 MiB total source, 6 MiB input and 16 MiB
output. Unknown fields, duplicate JSON keys, malformed encodings and exceeded
bounds reject the entire request (exit 2, diagnostic on stderr, no partial stdout).

Consumers must check the response schema, path order, source hashes, provider and
fact types/authority against their own admitted bytes before using any result.
Missing/older Core or a rejected batch must remain explicit unavailable coverage.
Neither a response digest nor provider text independently authenticates a binary.

## Optional JavaScript and TypeScript syntax

Install `diffwitness[structure]` to add the pinned Tree-sitter runtime and JS/TS
grammars. The engine retains an empty required-dependency list; no command
installs packages or accesses the network at runtime. The supported optional
suffixes are `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.mts` and `.cts`.
Both the transport and immutable Git-tree index select these same providers.
Recognized sources without the exact optional packages remain `parsed: false`
with empty facts and `unparsed` coverage. They are distinct from unknown suffixes,
which retain `file-only`/`unsupported` coverage.

Provider names are `tree-sitter-javascript` and `tree-sitter-typescript`.
Top-level named functions/classes, function-valued variables, class methods,
TS interfaces/types/enums and literal static imports/re-exports are observed
syntax. Qualified names use `relative/path.ts::Name`; module identity is the
relative source path. Name-only calls are inferred. Resolving relative imports
to one captured local source is also inferred; ambiguous candidates stay
unresolved. No project code, package resolver, runtime or type checker is invoked.

Nested declarations, computed methods, CommonJS assignment/require dependency
analysis, namespace/type resolution, escaped module literals and runtime dispatch
are not claimed. Grammar acceptance is not program correctness or type validity.
Duplicate materialized name/kind keys remain unparsed instead of silently choosing
a binding. Any syntax error, invalid UTF-8, native parse timeout or node limit
returns empty unparsed results for that file. Limits: existing 1 MiB source bound,
250 ms native parsing and 100k named syntax nodes. These are bounded extraction
limits, not a universal latency guarantee for a whole multi-file request.

The pinned runtime is 0.25.2: its retained native timeout avoids a reproduced
Python progress-callback crash on Python 3.12. The deprecated timeout API is used
deliberately and covered by a forced-expiration regression; no callback is used.
Before changing the pin, requalify that boundary and all three OS provider jobs.
The dependency-free standalone artifact currently reports optional languages as
unparsed; distribution of enhanced standalone artifacts remains a release gate.

Provider version/capability metadata is part of the index refresh key. Installing
or removing a grammar therefore forces a rebuild on the same Git tree. Python
results, identities and its AST provider remain unchanged. This unit covers the
listed JS/TS syntax; it does not complete all requested languages or consumers.

Primary parser references: [Python binding](https://github.com/tree-sitter/py-tree-sitter),
[JavaScript grammar](https://github.com/tree-sitter/tree-sitter-javascript),
[TypeScript grammar](https://github.com/tree-sitter/tree-sitter-typescript).


Ambient TypeScript wrappers (`declare`, including exported declarations) and
function/class-method signatures are retained as observed syntax. Signatures
have distinct kinds and no local runtime-call binding. Dotted extensionless
basenames such as `widget.test` resolve only when exactly one supported JS/TS
source candidate is captured; other-language sources are never selected by that
resolver. The extraction profile is versioned when adapter/resolver semantics
change so existing projections cannot retain the superseded behavior.

## Optional Go and Rust syntax

The same `structure` extra includes Go0.25.0 and Rust0.24.2 grammars for `.go`
and `.rs`, with the same pinned runtime and admission bounds. Provider names are
`tree-sitter-go` and `tree-sitter-rust`. Module identity remains the relative path;
qualified names are `path.go::Name` / `path.rs::Name`. Profile4 invalidates older
derived projections. Required dependencies remain empty.

Go facts include named functions, types/aliases/structs/interfaces and methods
on named receivers (including pointers/generics), plus grouped literal imports.
Rust facts include functions, modules, structs/enums/traits/unions/type aliases,
trait signatures and methods of named implementations. Nested module scope and
explicit trait-implementation names are retained in the syntactic qualifier.
Grouped/aliased `use`, `self`, wildcard and `extern crate` paths are observed;
comments inside a path never become part of its name. Identifier-only calls
remain inferred. Native-language imports stay external textual dependencies.

These facts do not resolve Go packages, Rust modules/types/traits, dependencies,
build flags, conditional compilation, macro expansion or runtime behavior.
Complex tuple/reference/associated implementation receivers are not resolved;
their methods are omitted rather than assigned an arbitrary child type. Escaped
Go import strings are omitted pending a language-specific decoder. A parsed file
means successful bounded syntax extraction, not complete semantic coverage.
No Go/Cargo build or project code executes. Missing/incompatible grammars and
invalid syntax retain empty unparsed coverage, as for JS/TS.

Primary grammars: [Go](https://github.com/tree-sitter/tree-sitter-go) and
[Rust](https://github.com/tree-sitter/tree-sitter-rust). Further requested languages,
all consumer adapters and enhanced standalone distribution remain open.

## Optional Java, Kotlin and C# syntax

The same `structure` extra pins Java0.23.5, Kotlin1.1.0 and C#0.23.5 grammars.
Suffixes `.java`, `.kt`, `.kts` and `.cs` select `tree-sitter-java`,
`tree-sitter-kotlin` and `tree-sitter-c-sharp`; language values are `java`,
`kotlin` and `csharp`. Profile5 refreshes prior derived projections. Python and
the existing optional languages retain their contracts and providers.

Named classes, interfaces, enums, records/structs, annotations, delegates,
objects/type aliases and named member methods are retained where those syntax
forms apply. Lexical package/namespace/nested-type scope enters the qualified
name: `Gateway.java::com.example.Gateway.refund`. Module identity remains the
source path. Source declarations/imports are OBSERVED, identifier-only calls
INFERRED. Java/C# named constructors and bodyless signatures have distinct kinds.
Alias names and comment trivia do not replace import targets; wildcard/global
qualifiers remain explicit. Imports stay external textual paths.

This is bounded syntax coverage. Overloaded declarations sharing a materialized
name/kind key remain empty/unparsed, pending a compatible overload identity model.
The pinned Kotlin grammar also rejects compact class members without a separator
before the same-line closing brace; the provider preserves empty unparsed coverage
without rewriting input. Anonymous/generated members, Kotlin secondary constructors,
complex generic import aliases, conditional-preprocessor declarations, annotation
processing, package/type resolution and extension/runtime dispatch are not claimed.
Strings/comments cannot invent declarations; real calls inside interpolation may
still appear as inferred syntax. No compiler, build tool or project code runs.

Required dependencies stay empty; missing/incompatible grammars, syntax errors,
invalid UTF-8 and shared source/native-time/node limits return empty unparsed
results. Installed optional wheels are qualified separately from dependency-free
skips. Other languages, all consumers and enhanced standalone distribution remain
open. Grammar version/API sources: [Java](https://github.com/tree-sitter/tree-sitter-java/blob/master/pyproject.toml),
[Kotlin](https://github.com/tree-sitter-grammars/tree-sitter-kotlin/blob/master/pyproject.toml),
[C#](https://github.com/tree-sitter/tree-sitter-c-sharp/blob/master/pyproject.toml).


## Optional Ruby and PHP syntax

The same structure extra adds Ruby0.23.1 and PHP0.24.1 for .rb and .php,
provider names tree-sitter-ruby/tree-sitter-php. Source-byte transport and
immutable-tree indexing share the same native250ms/no-callback boundary, exact
package admission and source/hash/authority contract. Profile6 refreshes prior
projections. Python remains dependency-free; absent grammars remain recognized
empty/unparsed. Nothing installs packages or executes project code at runtime.

Ruby lexical modules/classes, instance methods and self singleton methods have
source-bound names. PHP block/semicolon/global namespaces, named classes/interfaces/
traits/enums and methods/signatures retain lexical scope. Static quoted Ruby
require/require_relative and PHP use/require/include references are observed
syntax; require_relative receives an explicit ./ prefix if necessary. This does
not establish package ownership, filesystem resolution or execution. Ruby/PHP
identifier-only call expressions are INFERRED; ambiguous bare Ruby identifiers
are not guessed to be calls. PHP call targets are not linked by bare name because
the contract lacks call namespace and cannot safely choose between homonyms.

Comments, ordinary strings and heredoc/nowdoc bodies do not invent declarations.
Real interpolation calls remain syntax. Escaped/interpolated/dynamic import paths,
computed singleton receivers, generated/nested runtime declarations, metaprogramming,
package/type resolution and dispatch are omitted. Duplicate name/kind identities,
including repeated class reopening in one Ruby file, remain empty/unparsed rather
than arbitrarily selecting one declaration. Grammar acceptance is not runtime
correctness. Other suffixes, SQL/config and all consumer adoption remain separate.

Primary manifests: https://github.com/tree-sitter/tree-sitter-ruby/blob/master/pyproject.toml
and https://github.com/tree-sitter/tree-sitter-php/blob/v0.24.1/pyproject.toml .
PHP master0.24.2 was unavailable at package discovery; the released tagged0.24.1
pin was installed and its cross-platform wheels downloaded. Actual platform
qualification is required; download availability alone is not a behavior PASS.

## PR review4051931757 — parenthesized PHP paths

Actual regression FAILs before correction: require('client.php'), commented nested
include_once and triple-parenthesized require_once yield zero rather than three
static targets. Unwrap only one expression through each parenthesized node; skip
syntax comments, retain dynamic/concatenation omission. Installed multilingual
producer now asserts the parenthesized import. Profile6a invalidates initial6.

Final corrected589/585PASS/four skips56.434s;56 structural tests, compile/wheel/
installed protocol/pip check PASS. Fresh sequential10k append.860561/verify.381102/
rebuild.795546s,cold22.732/hotp9522.175ms PASS unchanged budgets. Initial base588
suite remains historical; corrected remote base/full suites must qualify the new
head. Initial#108 CI state preserved separately and does not qualify this change.
New exact24+3/review and fresh main required. All evidence remains MACHINE.


## Optional SQL and configuration keys

The same structure extra includes SQL0.3.11, JSON0.24.8, TOML0.7.0 and YAML0.7.2
for .sql/.json/.toml/.yaml/.yml. Provider names are tree-sitter-sql/json/toml/yaml,
module identity is the source path, and profile7a invalidates prior projections.
Existing exact-pin/native250ms/no-callback/source/hash/authority bounds apply.
No database, interpreter, custom YAML constructor or runtime environment runs.

SQL keeps top-level named table/view/index/function/type/schema DDL. Identifier
quoting and case are retained; source comments are excluded using actual syntax
trivia, including this grammar's marginalia nodes. Query/string/function-body
contents cannot invent outer declarations. No query/runtime dependency inference,
column semantics or dialect correctness claim. The tested CREATE PROCEDURE form
is rejected by this pinned grammar and remains empty/unparsed, not rewritten.

Configuration output contains only key names/positions and source hashes, never
values. Paths use / separators with ~0 for literal tilde and ~1 for literal slash;
array entries use their zero-based index. YAML documents have separate /@0,/@1
prefixes. TOML table declarations have config-table kind; keys have config-key.
Array-table child scopes follow their actual lexical occurrence. Quoted keys are
decoded with the appropriate supported parser; ambiguous/unsupported keys are not
guessed. JSON/TOML standard-library validation rejects duplicate/invalid forms.
YAML duplicate retained key identities fail closed; observations remain syntax-
only, without implicit type coercion or alias/merge expansion. Literal tag/anchor
syntax can surround actual mappings but is never executed. Complex/multiline or
YAML-only escaped keys remain unresolved, with no value-derived fallback facts.

JSON key paths containing invalid Unicode surrogates are empty/unparsed. No
configuration values, environment interpolation or loaded aliases enter
facts. This does not validate an application's config schema or executed setup.
Unsupported text formats keep existing file-only fallback. All consumers and
longitudinal identities still require their separate qualified adapters.

Primary grammars: https://github.com/DerekStride/tree-sitter-sql,
https://github.com/tree-sitter/tree-sitter-json,
https://github.com/tree-sitter-grammars/tree-sitter-toml and
https://github.com/tree-sitter-grammars/tree-sitter-yaml . Exact manifests and binary
wheel digests are recorded in qualification evidence; actual3OS tests are required.

JSON overflow values (including nested1e999) are explicitly rejected after strict
parsing; finite values/large integers remain valid. This does not redefine TOML
inf/nan syntax. Review4052729869 and fail-before evidence are retained.


## Detailed import references and literal loader syntax

Provider profile9 adds source-aware import references through the same extractor.
The default structure-request-1/structure-response-1 still returns exactly the
original import fields target and epistemic_status. Explicit structure-request-2
returns structure-response-2 with structure-extraction-2 files; each import adds
source_target, members, line and end_line. Unavailable details are null. Positions
are one-based inclusive source lines, admitted against the exact source bytes.

Python import retains written targets and observed from-import members. Package
initializers resolve relative lexical bases from their containing directory;
out-of-root references retain leading dots. Imported members are not presumed to
be modules. Only unique static local module candidates become INFERRED links;
ambiguous/unresolved targets remain neutral module-reference facts. This does not
resolve sys.path, namespace packages, runtime imports or external package owners.

JS/TS references now include direct literal require() and keyword import() calls,
using existing syntax nodes and position callbacks. Only nonempty unescaped
strings or single-line interpolation-free templates are admitted, optionally
parenthesized. import() allows its syntax options argument. Known require
bindings, function signatures, writes or eval/with barriers conservatively omit
CommonJS calls across the whole file. Aliased/member/optional loaders, computed,
interpolated and escaped targets remain unresolved. This observes syntax, not
execution, a proven Node binding or a package owner. Candidate local links remain
INFERRED. Native250ms and source/node bounds are unchanged; no second parser.

Other grammar adapters retain actual import positions; member/raw-target details
remain null until implemented. Code route/SQL-string/technology canonicalization,
full consumer citation coverage and longitudinal identity remain separate work.
