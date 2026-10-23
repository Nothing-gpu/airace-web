#!/usr/bin/env python3
"""Mutation-test rule J of _verify_site_feedback.py (no tester section on the landing page) in temporary copies, never live files.

Rule J was written first and watched failing against the page that still had the "Try it with eyes open." section. This puts
bits of that section back, one at a time, and demands that the check goes red for THAT reason and no other: exit 1, the expected
message, and every failing report is a J report. A commented-out copy must fail the source rule alone (remove means remove). The
control, the page as it is, must exit 0. Run one harness at a time; each run loads the site in a browser, so it takes a few minutes.

    PW_CHROMIUM=/path/to/chrome python3 _mutate_site_feedback.py
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ANCHOR = '<!-- =============== FAQ =============== -->'
SECTION = '<section class="sec"><div class="wrap">{}</div></section>'

# (what is put back, the html inserted before the FAQ, messages that must appear in the output, True when the rendered rule must fire too)
MUTATIONS = [
    ('an empty #testing section', '<section class="sec" id="testing"></section>',
     ['J: index.html still has an element with id="testing"', 'J: the #testing section is on the page'], True),
    ('a heading about eyes open', SECTION.format('<h2 class="h-sec">Take a look with eyes open.</h2>'),
     ['J: index.html still has the words "eyes open"', 'J: heading "Take a look with eyes open." is on the page'], True),
    ('one of the three cards', SECTION.format('<article class="page"><h3>Check your inputs</h3><p>Plain text.</p></article>'),
     ["J: index.html still has one of the section's three card headings", 'J: tester card "Check your inputs" is on the page'], True),
    ('the Developer-page test guide link', SECTION.format('<p><a href="https://docs.airacegp.com/customizing.html#dev">Developer-page test guide</a></p>'),
     ['J: index.html still has a link to the Developer-page test guide', 'J: link to the Developer-page test guide'], True),
    ('a commented-out copy of the section', '<!-- <section class="sec" id="testing"><h2>Try it with eyes open.</h2></section> -->',
     ['J: index.html still has an element with id="testing"', 'J: index.html still has the words "eyes open"'], False),
]


def run_check(site):
    env = dict(os.environ)
    r = subprocess.run([sys.executable, '-B', '_verify_site_feedback.py'], cwd=site, env=env, capture_output=True, text=True, timeout=1200)
    return r.returncode, r.stdout


def main():
    survivors = []
    with tempfile.TemporaryDirectory(prefix='site-feedback-mutations-') as td:
        site = Path(td) / 'site'

        def fresh():
            if site.exists():
                shutil.rmtree(site)
            shutil.copytree(HERE, site, ignore=shutil.ignore_patterns('.git', '__pycache__'))

        for name, html, expect, rendered in MUTATIONS:
            fresh()
            page = site / 'index.html'
            text = page.read_text(encoding='utf-8')
            if text.count(ANCHOR) != 1:
                print(f'CRASH  {name}: the anchor occurs {text.count(ANCHOR)} times, not once')
                return 2
            page.write_text(text.replace(ANCHOR, html + '\n' + ANCHOR), encoding='utf-8')
            code, out = run_check(site)
            fails = [ln for ln in out.splitlines() if ln.startswith('FAIL')]
            why = []
            if code != 1:
                why.append(f'exit {code}, wanted 1')
            for msg in expect:
                if msg not in out:
                    why.append(f'missing "{msg}"')
            other = [ln for ln in fails if 'J)' not in ln]
            if other:
                why.append(f'also failed for another reason: {other[0][:80]}')
            has_rendered = any('requirements (A-F, J)' in ln for ln in fails)
            if has_rendered != rendered:
                why.append('the rendered rule ' + ('did not fire' if rendered else 'fired, but a comment is not visible'))
            print(('SURVIVED ' if why else 'KILLED   ') + name + ('  (' + '; '.join(why) + ')' if why else ''))
            if why:
                survivors.append(name)

        fresh()
        code, out = run_check(site)
        if code != 0:
            print('CONTROL FAILED: the unmutated page does not pass')
            survivors.append('control')
        else:
            print('control: the page as it is passes')
    total = len(MUTATIONS)
    print(f'{total - len([s for s in survivors if s != "control"])}/{total} mutations killed' + ('' if not survivors else '; problems: ' + ', '.join(survivors)))
    return 1 if survivors else 0


if __name__ == '__main__':
    sys.exit(main())
