# DiffWitness release process

A public DiffWitness release should be boring, reproducible, and tied to a tested Git tag.

## Release prerequisites

Before cutting a tag:

1. the release PR is merged to `main`;
2. the full supported CI matrix is green;
3. `python benchmarks/proofbench.py` is green;
4. package/runtime versions agree;
5. plugin manifests and certificate schema parse;
6. the repository is public under its final community-facing name;
7. GitHub Action examples point at a stable release tag rather than a moving `main` branch.

Never cut a release merely to bypass a red or unavailable proof/test gate.

## Version

DiffWitness follows semantic versioning for public contracts.

For v0.x releases, certificate schema/prefix changes, CLI behavior, plugin manifests and Action inputs/outputs are all treated as compatibility-sensitive even though the project is pre-1.0.

## Tag

Create an annotated/signed tag from the exact tested `main` commit where possible:

```bash
git tag -s v0.3.0 -m "DiffWitness 0.3.0"
git push origin v0.3.0
```

The `release` workflow builds from the tag itself.

## Generated assets

The release workflow produces:

- Python wheel;
- source distribution;
- standalone `dw` binaries for GitHub-hosted Linux/macOS/Windows runners;
- per-binary `BUILD.json` containing platform and SHA-256;
- a combined `SHA256SUMS.txt`;
- GitHub Release notes generated from repository history.

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

Community examples should move from:

```yaml
uses: TFourniax/tooltest@main
```

to the final public repository and a release ref, for example:

```yaml
uses: TFourniax/diffwitness@v0.3.0
```

Security-sensitive users can pin the immutable commit SHA behind the tag.

## Binary provenance roadmap

The v0.3 release workflow records hashes. Stronger public releases should add artifact attestations/signing (for example GitHub artifact attestations / Sigstore) before claiming authenticated binary provenance.

That provenance layer is separate from a DiffWitness causal certificate: one authenticates the **tool artifact**, the other describes evidence about the **candidate patch**.
