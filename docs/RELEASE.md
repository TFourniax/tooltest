# DiffWitness release process

A public DiffWitness release should be boring, reproducible, and tied to a tested Git tag.

## Release prerequisites

Before cutting a tag:

1. the release PR is merged to `main`;
2. the full supported CI matrix is green;
3. `python benchmarks/proofbench.py` is green;
4. package/runtime versions agree;
5. plugin manifests and certificate schema parse;
6. the repository is public under its **final community-facing name**;
7. GitHub Action examples and `diffwitness init` point at that final repository plus the exact release tag rather than a moving `main` branch;
8. the release-package and standalone-binary preflight jobs are green on the release candidate commit.

Never cut a release merely to bypass a red or unavailable proof/test gate.

The current alpha version is `0.4.0a1`. The code can be technically alpha-ready before the public repository rename is performed, but do not publish the first community tag while examples still rely on a temporary repository identity.

## Version

DiffWitness follows semantic versioning for public contracts.

For v0.x releases, certificate schema/prefix changes, CLI behavior, plugin manifests, Debt Ledger semantics, and Action inputs/outputs are all treated as compatibility-sensitive even though the project is pre-1.0.

## Tag

Create an annotated/signed tag from the exact tested `main` commit where possible:

```bash
git tag -s v0.4.0a1 -m "DiffWitness 0.4.0a1"
git push origin v0.4.0a1
```

The `release` workflow builds from the tag itself and validates that the tag name agrees with the installed package version. Do not move a published release tag after users may have pinned it.

## Generated assets

The release workflow produces:

- Python wheel;
- source distribution;
- standalone `dw` binaries for GitHub-hosted Linux/macOS/Windows runners;
- per-binary `BUILD.json` containing platform and SHA-256;
- a combined `SHA256SUMS.txt`;
- GitHub Release notes generated from repository history.

The PR CI also builds and smokes the real wheel/sdist and standalone binaries before merge, so the tag workflow is not the first time these paths execute.

Standalone binaries are convenience artifacts, not a cryptographic supply-chain signature.

## PyPI

The workflow contains an opt-in PyPI Trusted Publishing job.

Configure a PyPI Trusted Publisher for this repository/environment and set the repository variable:

```text
DIFFWITNESS_PYPI_PUBLISH=true
```

No long-lived PyPI API token should be stored when Trusted Publishing is available.

Then a tagged release can publish the wheel/sdist through OIDC.

## GitHub Action pinning

The intended final public repository name is currently:

```text
TFourniax/diffwitness
```

Once the repository has that final identity, release examples should use the exact alpha tag:

```yaml
uses: TFourniax/diffwitness@v0.4.0a1
```

Security-sensitive users can pin the immutable commit SHA behind the tag. Avoid `@main` for a merge gate: a moving branch can change verification behavior without a consuming repository changing its workflow.

`diffwitness init` deliberately emits a version-tagged Action reference. Therefore the repository identity used by that generator must be updated to the final public name before the first community release is tagged.

## Pull-request gate governance

DiffWitness's composite Action evaluates proof/debt policy from the **trusted base revision's** `.diffwitness.toml`, not from the candidate revision. A PR therefore cannot weaken its own DiffWitness config and have that weakened config judge the same PR.

That does not make GitHub workflow files themselves immutable. If a repository treats DiffWitness as a required merge control, protect the workflow/ruleset that invokes it using GitHub governance appropriate to the organization (for example a required workflow/ruleset or mandatory review of workflow changes). Do not claim that a `pull_request` workflow which a contributor is free to rewrite is itself a tamper-proof policy authority.

For untrusted candidate code, keep the execution token read-only, expose no secrets, and use disposable runners as described in [`../SECURITY.md`](../SECURITY.md).

## Binary provenance roadmap

The v0.4 alpha release workflow records hashes. Stronger public releases should add artifact attestations/signing (for example GitHub artifact attestations / Sigstore) before claiming authenticated binary provenance.

That provenance layer is separate from a DiffWitness causal certificate: one authenticates the **tool artifact**, the other describes evidence about the **candidate patch**.