#!/usr/bin/env python3
"""Prove the motion geometry check detects escaped and missing success markers."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent

def main():
    with tempfile.TemporaryDirectory(prefix='motion-mutations-') as td:
        site = Path(td) / 'site'
        shutil.copytree(ROOT, site, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        page = site / 'index.html'
        original = page.read_text()
        def run():
            for cache in site.rglob('__pycache__'):
                shutil.rmtree(cache)
            return subprocess.run([sys.executable, '-B', str(site / '_verify_motion_bounds.py')],
                                  capture_output=True, text=True, env=os.environ)
        result = run()
        if result.returncode:
            print('FAIL baseline\n' + result.stdout + result.stderr)
            return 1
        cases = [
            ('remove success-marker space', '.node .state{padding-inline:4px;', '.node .state{'),
            ('remove success enlargement', 'transform:scale(1.5)', 'transform:scale(1)'),
        ]
        bad = 0
        for name, before, after in cases:
            if original.count(before) != 1:
                print('ANCHOR MISS ' + name)
                bad += 1
                continue
            try:
                page.write_text(original.replace(before, after))
                assert page.read_text() != original
                result = run()
                caught = result.returncode == 1 and 'FAIL ' in result.stdout and 'CRASH' not in result.stdout
                print(('KILLED ' if caught else 'SURVIVED/CRASH ') + name)
                bad += not caught
            finally:
                page.write_text(original)
                assert page.read_text() == original
        result = run()
        bad += result.returncode != 0
        print(f'{len(cases) - bad}/{len(cases)} mutations killed; restored baseline exit {result.returncode}')
        return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
