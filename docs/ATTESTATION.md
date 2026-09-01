# DiffWitness attestations

A proof is useful only while it still refers to the code that was actually tested.

DiffWitness evidence certificates are content-addressed and can be checked against the current repository tree.

## Verify a certificate

```bash
dw verify evidence.json
```

The command checks two independent properties:

1. **Integrity** — does the certificate id still match its content?
2. **Freshness** — does the certificate's candidate Git tree still match the requested repository state?

Example:

```text
certificate: dw2_...
integrity:   valid
freshness:   fresh against WORKTREE
base:        resolvable
verdict:     VALID
```

Change source content after the proof and the same certificate becomes:

```text
freshness:   stale
verdict:     INVALID
```

## Tree identity, not commit identity

Guard commonly proves an uncommitted working tree. The developer may then create a Git commit containing exactly that content.

A SHA-only verifier would incorrectly invalidate the proof because the ephemeral snapshot SHA differs from the new commit SHA.

DiffWitness therefore compares **Git tree ids**. If the committed files are byte-for-byte the same tree that was proved, the certificate can remain fresh.

```bash
dw verify evidence.json --against HEAD
```

## Generated proof artifacts

If `evidence.json` itself is written as an untracked file inside the repository after candidate capture, it must not make its own proof stale.

`dw verify` automatically excludes the certificate file itself **only when it is untracked**. A tracked certificate is repository content and is never silently ignored.

Other generated artifacts can be made explicit:

```bash
dw verify evidence.json \
  --ignore-artifact evidence.md \
  --ignore-artifact .diffwitness/run.log
```

These exclusions affect only the ephemeral verification snapshot. DiffWitness does not alter the working tree or real Git index.

## Attach proof to a commit

Once a certificate is valid against a commit:

```bash
dw note evidence.json --commit HEAD
```

DiffWitness first verifies integrity and tree freshness. It refuses a stale or altered certificate.

On success it stores a compact proof reference in:

```text
refs/notes/diffwitness
```

without changing the commit SHA.

Publish the note explicitly:

```bash
git push origin refs/notes/diffwitness
```

This gives teams a Git-native way to associate a commit with its proof without putting generated evidence blobs inside the source tree.

## Machine-readable verification

```bash
dw verify evidence.json --json
```

returns fields including:

- certificate id;
- integrity verdict;
- freshness verdict;
- certificate candidate tree;
- current tree;
- whether the base object is still resolvable;
- explicitly ignored generated artifacts;
- final boolean validity.

## What attestation does not prove

Integrity means the certificate has not been modified without changing its content address. Freshness means it still refers to the same Git tree.

Neither property proves that the original evidence command was sufficient to capture every software requirement. That boundary remains explicit in the proof protocol.
