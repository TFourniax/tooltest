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
