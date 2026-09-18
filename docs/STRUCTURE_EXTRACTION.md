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
