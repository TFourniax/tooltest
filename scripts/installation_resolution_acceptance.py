"""Exercise actual installed launchers and generated hooks with competing PATH entries.

Run with --wheel PATH [--pipx] [--standalone PATH]. No provider approval is
simulated: machine hook execution checks installation identity, not human trust.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

WINDOWS = os.name == 'nt'


def run(args, *, cwd, env, payload=None):
    proc = subprocess.run(args, cwd=cwd, env=env, input=payload, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          shell=isinstance(args, str), timeout=180)
    if proc.returncode:
        raise AssertionError(f'{args!r}: {proc.returncode}\n{proc.stdout}\n{proc.stderr}')
    return proc.stdout


def launcher(root, name):
    return root / ('Scripts' if WINDOWS else 'bin') / (name + ('.exe' if WINDOWS else ''))


def mark_install(python, label, root, env, *, user=False):
    query = 'import site; print(site.getusersitepackages())' if user else 'import sysconfig; print(sysconfig.get_path("purelib"))'
    directory = Path(run([str(python), '-c', query], cwd=root, env=env).strip())
    directory.mkdir(parents=True, exist_ok=True)
    # Test-only marker in each disposable consumer environment proves which
    # interpreter executes the real generated hook, independently of its text.
    (directory / 'sitecustomize.py').write_text(
        'import os\n'
        'if os.environ.get("DW_INSTALLATION_PROBE"):\n'
        '    with open(os.environ["DW_INSTALLATION_PROBE"], "a", encoding="utf-8") as probe:\n'
        f'        probe.write({label!r} + "\\n")\n', encoding='utf-8')


def commands(value):
    if isinstance(value, dict):
        if isinstance(value.get('command'), str):
            yield value
        for item in value.values():
            yield from commands(item)
    elif isinstance(value, list):
        for item in value:
            yield from commands(item)


def fixture(root, label, env):
    repo = root / ('project ' + label)
    repo.mkdir()
    for args in (['init', '-q'], ['config', 'user.name', 'Installation Acceptance'],
                 ['config', 'user.email', 'installation@example.invalid']):
        run(['git', *args], cwd=repo, env=env)
    (repo / 'app.py').write_text('print("ok")\n', encoding='utf-8')
    run(['git', 'add', 'app.py'], cwd=repo, env=env)
    run(['git', 'commit', '-qm', 'fixture'], cwd=repo, env=env)
    (repo / '.codex').mkdir()
    return repo


def exercise(root, label, invocation, expected, expected_marker, competing, env, *, native=True):
    env = {**env, 'PATH': str(competing.parent) + os.pathsep + env['PATH']}
    repo = fixture(root, label, env)
    call = lambda *args: run([*map(str, invocation), *args], cwd=repo, env=env)
    if native:
        call('setup', 'install', '--agent', 'codex', '--json')
        owner = json.loads((repo / '.idleproof/integration.json').read_text())['diffwitnessCommand']
        assert Path(owner) == expected.resolve(), (label, owner, expected)
    call('protect', 'enable', '--force', '--json')
    owner = json.loads((repo / '.git/diffwitness/protect.json').read_text())['diffwitnessCommand']
    assert Path(owner) == expected.resolve(), (label, owner, expected)
    hooks_path = repo / '.codex/hooks.json'
    before = hooks_path.read_bytes()
    hooks = json.loads(before)['hooks']
    if native:
        initial = json.loads(call('status', '--json'))
        assert initial['readiness']['native']['installed'] is True, initial
        assert initial['setup']['native_ready'] is False, initial
        assert initial['readiness']['native']['adapters']['codex']['providerTrust'] == 'unknown', initial
    assert set(hooks) == ({'SessionStart', 'UserPromptSubmit', 'Stop', 'PreToolUse', 'PostToolUse'} if native else {'PreToolUse', 'PostToolUse'}), hooks
    for entry in commands(hooks):
        assert str(expected.resolve()) in entry['command'], (label, entry)
    # Execute generated native SessionStart and Protect Pre/Post through the
    # same shell/argv form consumed by the provider, then check live receipts.
    events = ['SessionStart'] if native else []
    events += ['PreToolUse', 'PostToolUse']
    probe = repo / '.git/installation-probe.txt'
    for event in events:
        probe.unlink(missing_ok=True)
        entry = next(commands(hooks[event]))
        command = [entry['command'], *entry['args']] if 'args' in entry else entry['command']
        payload = json.dumps({'provider': 'codex', 'session_id': label, 'cwd': str(repo),
                              'tool_name': 'shell', 'tool_input': {'command': 'git status --short'},
                              'tool_response': {'exit_code': 0, 'stdout': ''}})
        run(command, cwd=repo, env={**env, 'DW_INSTALLATION_PROBE': str(probe)}, payload=payload)
        observed = probe.read_text().splitlines() if probe.exists() else []
        if expected_marker is not None:
            assert observed and set(observed) == {expected_marker}, (label, event, observed)
        else:
            assert not observed, (label, 'frozen hook unexpectedly used Python install', observed)
    status = json.loads(call('protect', 'status', '--json'))
    assert status['adapters']['codex']['activeSeen'] is True, status
    assert (repo / '.git/diffwitness/protection.jsonl').is_file(), label
    if native:
        project = json.loads(call('status', '--json'))
        setup = json.loads(call('setup', 'status', '--json'))
        assert project['setup']['native_ready'] is True, project
        assert project['readiness'] == setup['readiness'], (project, setup)
        assert project['readiness']['currentProof']['currentTreeVerified'] is False, project
    # A competing installation on PATH must not change hook identity on re-enable.
    call('protect', 'disable', '--json')
    call('protect', 'enable', '--force', '--json')
    assert hooks_path.read_bytes() == before, label
    assert not (repo / '.claude').exists(), label
    print(f'PASS {label}: hooks target and execute {expected.resolve()}', flush=True)
    return repo, before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', required=True, type=Path)
    parser.add_argument('--pipx', action='store_true')
    parser.add_argument('--standalone', type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    base_python = str(Path(getattr(sys, '_base_executable', sys.executable)).absolute())
    env = {k: v for k, v in os.environ.items() if k not in {
        'DIFFWITNESS_BIN', 'DIFFWITNESS_IDLEPROOF_BIN', 'PYTHONPATH', 'PYTHONHOME',
        'PYTHONUSERBASE', 'PYTHONNOUSERSITE', 'VIRTUAL_ENV', 'DW_INSTALLATION_PROBE'}}
    env['PYTHONUTF8'] = '1'
    with tempfile.TemporaryDirectory(prefix='dw-installation-') as td:
        root = Path(td).resolve()
        locations = {}
        for label in ('A', 'B'):
            install = root / ('installation ' + label)
            run([base_python, '-m', 'venv', str(install)], cwd=root, env=env)
            python = launcher(install, 'python')
            run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], cwd=root, env=env)
            mark_install(python, label, root, env)
            locations[label] = (python, launcher(install, 'dw'))
        ap, a = locations['A']; bp, b = locations['B']
        if args.standalone:
            binary = args.standalone.resolve()
            exercise(root, 'frozen', [binary], binary, None, b, env, native=False)
            return 0
        repo, before = exercise(root, 'A-PATH-B', [a], a, 'A', b, env)
        exercise(root, 'B-PATH-A', [b], b, 'B', a, env)
        exercise(root, 'module-A', [ap, '-m', 'diffwitness.entry'], a, 'A', b, env)
        exercise(root, 'override-B', [a], b, 'B', a, {**env, 'DIFFWITNESS_BIN': str(b)})
        # Same-path upgrade/reinstall keeps executable ownership and hook bytes.
        for options in (['--upgrade', '--force-reinstall'],):
            run([str(ap), '-m', 'pip', 'install', '--no-index', '--no-deps', *options, str(wheel)], cwd=root, env=env)
        cycle_env = {**env, 'PATH': str(b.parent) + os.pathsep + env['PATH']}
        for action in ('disable', 'enable'):
            run([str(a), 'protect', action, '--json'], cwd=repo, env=cycle_env)
        assert (repo / '.codex/hooks.json').read_bytes() == before
        # A different CLI must still remove hooks owned by the persisted A path.
        run([str(b), 'protect', 'disable', '--json'], cwd=repo, env=cycle_env)
        run([str(b), 'setup', 'uninstall', '--json'], cwd=repo, env=cycle_env)
        assert not (repo / '.codex/hooks.json').exists()
        run([str(ap), '-m', 'pip', 'uninstall', '-y', 'diffwitness'], cwd=root, env=env)
        assert not a.exists()
        run([str(ap), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], cwd=root, env=env)
        exercise(root, 'reinstalled-A', [a], a, 'A', b, env)
        user_env = {**env, 'PYTHONUSERBASE': str(root / 'user install')}
        run([base_python, '-m', 'pip', 'install', '--user', '--ignore-installed', '--no-index', '--no-deps', str(wheel)], cwd=root, env=user_env)
        user_dw = Path(run([base_python, '-c', 'import sysconfig; print(sysconfig.get_path("scripts", scheme=sysconfig.get_preferred_scheme("user")))'], cwd=root, env=user_env).strip()) / ('dw.exe' if WINDOWS else 'dw')
        mark_install(base_python, 'USER', root, user_env, user=True)
        exercise(root, 'pip-user', [user_dw], user_dw, 'USER', b, user_env)
        exercise(root, 'pip-user-module', [base_python, '-m', 'diffwitness.entry'], user_dw, 'USER', b, user_env)
        if args.pipx:
            pipx_env = {**env, 'PIPX_HOME': str(root / 'pipx-home'), 'PIPX_BIN_DIR': str(root / 'pipx-bin'), 'PIPX_MAN_DIR': str(root / 'pipx-man')}
            run([sys.executable, '-m', 'pipx', 'install', '--python', base_python, '--pip-args=--no-index', str(wheel)], cwd=root, env=pipx_env)
            pipx_root = root / 'pipx-home/venvs/diffwitness'
            mark_install(launcher(pipx_root, 'python'), 'PIPX', root, pipx_env)
            pipx_dw = root / 'pipx-bin' / ('dw.exe' if WINDOWS else 'dw')
            exercise(root, 'pipx', [pipx_dw], pipx_dw, 'PIPX', b, pipx_env)
        else:
            print('pipx not requested in this run; required separately by CI', flush=True)
    print('Installation resolution consumer acceptance PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
