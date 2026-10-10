#!/usr/bin/env python3
"""The animated model-chain success marker fits its label, including at zoom.

Written after _verify_a11y.py exposed a 200%-zoom failure, BEFORE its fix.
Force each real .node.ok state: waiting for the animation to happen is flaky.
The production CSS must still enlarge the dot, but no side may escape its
label by more than the existing clipping check's 1 px tolerance.

PW_CHROMIUM=/usr/bin/chromium python3 _verify_motion_bounds.py
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import sys
import threading
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    failures = []
    try:
        with sync_playwright() as p:
            executable = os.environ.get('PW_CHROMIUM') or os.environ.get('PW_CHROME')
            browser = p.chromium.launch(**({'executable_path': executable} if executable else {}))
            for width in (320, 390, 720, 1440):
                page = browser.new_page(viewport={'width': width, 'height': 450})
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html', wait_until='networkidle')
                page.evaluate('document.fonts.ready.then(() => true)')
                page.add_style_tag(content='*{transition:none!important}')
                rows = page.evaluate("""() => {
                  document.documentElement.classList.add('motion');
                  const chain = document.querySelector('[data-chain]');
                  chain.setAttribute('data-step', '');
                  const nodes = [...chain.querySelectorAll('.node')];
                  return nodes.map(node => {
                    node.classList.add('ok');
                    const state = node.querySelector('.state').getBoundingClientRect();
                    const dot = node.querySelector('.state i').getBoundingClientRect();
                    return {grown: dot.width >= 8.9 && dot.height >= 8.9,
                      fits: dot.left >= state.left-1 && dot.right <= state.right+1 &&
                            dot.top >= state.top-1 && dot.bottom <= state.bottom+1,
                      leftOverflow: state.left-dot.left};
                  });
                }""")
                ok = len(rows) == 3 and all(row['grown'] and row['fits'] for row in rows)
                print(('PASS ' if ok else 'FAIL ') + f'{width}px success markers: {rows}')
                if not ok:
                    failures.append(width)
                page.close()
            browser.close()
    finally:
        server.shutdown()
    print(f'{len(failures)} motion-bound failure(s)')
    return 1 if failures else 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'CRASH: {exc!r}')
        sys.exit(2)
