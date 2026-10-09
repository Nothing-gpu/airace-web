#!/usr/bin/env python3
"""Mutation-test the published claim contract in temporary copies, never live files.

Every mutation asserts its anchor actually changed, demands exit 1 plus the
expected FAIL category (a CRASH is not a catch), and checks a clean baseline
again after restoring. No Python imports of mutated app code; -B and removal
of __pycache__ prevent stale bytecode. Run one harness at a time.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
APP = Path(os.environ.get('AIRACE_APP', HERE.parent / 'airarce-ui' / 'airacee' / 'airacee'))
WEB = Path(os.environ.get('AIRACE_WEB', HERE if (HERE / 'llms-full.txt').exists() else HERE.parent / 'airace-web'))

def main():
    with tempfile.TemporaryDirectory(prefix='site-mutations-') as td:
        root = Path(td)
        site = root / 'site'
        web = site if HERE == WEB else root / 'web'
        app = root / 'airarce-ui' / 'airacee' / 'airacee'
        for src, dst in [(HERE, site), (WEB, web)]:
            dst.mkdir(exist_ok=True)
            for p in src.iterdir():
                if p.is_file() and p.suffix in {'.py','.md','.html','.txt'}:
                    shutil.copy2(p, dst / p.name)
        app.mkdir(parents=True)
        shutil.copy2(APP / 'run.py', app / 'run.py')
        shutil.copy2(APP.parents[1] / 'AGENTS.md', app.parents[1] / 'AGENTS.md')
        env = dict(os.environ, AIRACE_APP=str(app), AIRACE_WEB=str(web))
        command = [sys.executable, '-B', str(site / '_verify_llms.py')]
        def run():
            for cache in root.rglob('__pycache__'):
                shutil.rmtree(cache)
            return subprocess.run(command, env=env, capture_output=True, text=True)
        baseline = run()
        if baseline.returncode:
            print('FAIL baseline must pass before mutations\n' + baseline.stdout + baseline.stderr)
            return 1
        cases = []
        rows = [line.strip('|').split('|') for line in (site / 'CLAIMS.md').read_text().splitlines()
                if line.startswith('| ') and not line.startswith('| ID ')]
        for ident, _, _, wording, _ in rows:
            cases.append(('remove long-form ' + ident.strip(), web / 'llms-full.txt', wording.strip(), '[removed]', 'claim: ' + ident.strip()))
        cases += [
            ('invent HTML setting', site / 'index.html', '</main>', '<p data-setting="invented_mode">Invented setting</p></main>', 'setting:'),
            ('remove manifest', site / 'CLAIMS.md', (site / 'CLAIMS.md').read_text(), '# Empty manifest\n', 'manifest:'),
            ('invent source', site / 'CLAIMS.md', 'Driver memory across sessions (2026-10-06)', 'Section that does not exist', 'source:'),
            ('change live app default', app / 'run.py', "'driver_memory':      True", "'driver_memory':      False", 'default:'),
            ('remove live config key', app / 'run.py', "'spotter_mode': 'off'", "'spotter_removed': 'off'", 'setting:'),
            ('hide feature in comment', web / 'llms-full.txt', rows[0][3].strip(), '<!-- ' + rows[0][3].strip() + ' -->', 'claim: memory'),
        ]
        if (site / 'customizing.html').exists():
            cases += [
                ('unregistered prose setting', site / 'customizing.html', '<ul>', '<ul><li><strong>Magic grip</strong>: on.</li>', 'setting:'),
                ('wrong visible default', site / 'customizing.html', '<span data-default="driver_memory">Default: on.</span>', '<span data-default="driver_memory">Default: off.</span>', 'default:'),
            ]
        else:
            cases += [
                ('invent Markdown setting', site / 'llms-full.txt', '## Customization', '[setting: invented_mode]\n\n## Customization', 'setting:'),
                ('wrong visible default', site / 'llms-full.txt', '[setting: driver_memory] Default: on.', '[setting: driver_memory] Default: off.', 'default:'),
            ]
        # These probes exercise guards that can already pass on old content.
        cases += [
            ('fabricate source excerpt', site / 'CLAIMS.md', 'keeps the last 8 sessions per game + track + car', 'keeps an imaginary unlimited history', 'source:'),
            ('insert universal wheel claim', site / 'index.html', '</main>', '<p>Works with every wheel.</p></main>', 'policy:'),
            ('insert split benchmark score', site / 'index.html', '</main>', '<p><span>80</span><span>/80</span></p></main>', 'policy:'),
            ('insert performance pitch', site / 'index.html', '</main>', '<p>80 of 80 answers right.</p></main>', 'policy:'),
            ('insert donation pitch', site / 'index.html', '</main>', '<p>Support with voluntary Ko-fi tips.</p></main>', 'policy:'),
        ]
        if (site / 'llms.txt').exists():
            for feature in ('Driver memory', 'Strategy planner', 'Setup advice', 'Spotter', 'Developer tools'):
                line = next(line for line in (site / 'llms.txt').read_text().splitlines() if line.startswith('- [' + feature + ']'))
                cases.append(('comment out short ' + feature, site / 'llms.txt', line, '<!-- ' + line + ' -->', 'short:'))
        for ident in ('model-default', 'f1-questions'):
            line = next(line for line in (site / 'CLAIMS.md').read_text().splitlines()
                        if line.startswith('| ' + ident + ' |'))
            cases.append(('remove required row ' + ident, site / 'CLAIMS.md', line, '', 'manifest:'))
        failed = 0
        for name, path, old, new, reason in cases:
            original = path.read_text()
            if old not in original or old == new:
                print('ANCHOR MISS ' + name)
                failed += 1
                continue
            mutated = original.replace(old, new)
            assert mutated != original
            try:
                path.write_text(mutated)
                result = run()
                killed = result.returncode == 1 and 'FAIL ' + reason in result.stdout and 'CRASH' not in result.stdout
                print(('KILLED ' if killed else 'CRASH ' if result.returncode == 2 else 'SURVIVED ') + name)
                if not killed:
                    print(result.stdout + result.stderr)
                    failed += 1
            finally:
                path.write_text(original)
                assert path.read_text() == original
        restored = run()
        if restored.returncode:
            print('FAIL restored baseline\n' + restored.stdout + restored.stderr)
            failed += 1
        print(f'{len(cases) - failed}/{len(cases)} mutations killed; restored baseline exit {restored.returncode}')
        return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
