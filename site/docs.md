# DiffWitness alpha quickstart

Requirements: Python 3.11+ and Git.

    pipx install .
    dw --version
    dw doctor

Choose optional runtime protection:

    dw protect detect
    dw protect enable --policy standard
    dw protect use external
    dw protect disable

Run an agent through Guard:

    dw guard -- claude
    dw guard -- codex

Gate an existing change:

    dw gate --base origin/main --candidate HEAD

Inspect and repay debt:

    dw debt
    dw health
    dw plan
    dw repay --prompt-only

Explain and change presentation level:

    dw explain
    dw view guided
    dw view technical

Full human page: /docs/
Exact repository documentation: https://github.com/TFourniax/tooltest/tree/rc/human-test-final-2026-09-01/docs
