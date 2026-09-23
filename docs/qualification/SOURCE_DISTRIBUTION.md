# RR-006 — runnable source qualification distribution

A/REL.01 and B/AD-07 require the tests shipped in the sdist to have their actual
assets. On Core d383b4b the actual extracted source distribution has142test
modules, but the properly isolated installed-source suite fails6tests and14errors,
with51skips (730tests total). Missing assets include schemas, fixture JSON,
plugin manifests, hooks/integrations, benchmark scripts and release-policy files.

MANIFEST.in now includes the suite's real assets, with generated Python caches
excluded. A new source-distribution preflight runs the included suite outside
the checkout, in its own editable installation and virtual environment. The
existing release package job requires it and uploads its raw log even on failure.
The canonical tracked test inventory must match the archive byte for byte; no
assertion, skip, budget or existing gate is removed. No package is published.

After integrating current main8ef8d6322cb1aa73c8c30357c64c2f48bec3aab8,
the actual source archive has143test modules; its full733tests pass with52explicit
platform/optional-dependency skips in87.615s. Archive SHA256:
c67de215ff843382f2761460d2423a00fc40fee559411004e939a5cccbf1763c.
Final documentation/metadata additions follow this local build; final artifact
identity must come from final-head CI. The local hash is not a published artifact.

## Harness errors retained

The first build frontend invocation failed because the build module was absent;
the already installed setuptools backend then produced the actual sdist.
Initial harness variants put extracted src first in PYTHONPATH while using
entrypoints belonging to another location. That correctly fails the installation
identity guard (10failures/44errors before asset correction;4failures/30errors
after). An editable installation with the same forced PYTHONPATH still shadows
its installed metadata with source egg-info. These are harness defects, not new
product failures. The final harness removes that override and uses a fresh editable
installation of the exact extracted source. Its baseline then reproduces exactly
the missing-asset6failures/14errors, and its candidate passes all733tests. All
attempts, full logs and hashes are retained beside this document.

Fresh final-head review/CI and exact-main requalification remain required.
RR006 publication, immutable coordinated release manifest and #80 actual public-tag
consumer stay open. No HUMAN or Alpha-ready status follows from this source gate.
