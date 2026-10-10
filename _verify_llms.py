#!/usr/bin/env python3
"""Claim and setting contract, written before the site refresh (2026-10-08).

CLAIMS.md is a Markdown table: id | AGENTS heading | exact source excerpt |
required public wording | comma-separated files (optionally #section).
Every row must reach llms-full.txt. @web/ resolves AIRACE_WEB (sibling by default).
Source excerpts are checked within their named AGENTS.md section, not anywhere.
HTML comments/scripts/styles/hidden nodes cannot satisfy a content requirement.

Settings use data-setting="config_key ..." on their documentation item; Markdown
uses [setting: config_key]. All config keys are read with AST from the real app,
without importing run.py or copying _CONFIG_DEFAULT. In customizing.html every
setting list item must be annotated, so an unregistered item fails too. Arbitrary
prose elsewhere still needs human review: this is not a natural-language prover.

Run: python3 _verify_llms.py. AIRACE_APP and AIRACE_WEB override sibling paths.
"""
from __future__ import annotations
import ast
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
APP = Path(os.environ.get('AIRACE_APP', ROOT.parent / 'airarce-ui' / 'airacee' / 'airacee'))
WEB = Path(os.environ.get('AIRACE_WEB', ROOT if (ROOT / 'llms-full.txt').exists() else ROOT.parent / 'airace-web'))
REQUIRED = {'memory', 'memory-data', 'memory-controls', 'memory-limits', 'strategy',
            'strategy-limits', 'setup', 'setup-limits', 'spotter', 'spotter-audio',
            'spotter-limits', 'dev-wheel', 'dev-cadence', 'dev-lmu', 'dev-spotter',
            'dev-limits', 'lmu', 'radio', 'fallback', 'coaching', 'model-default', 'f1-questions'}
SETTING_SECTIONS = {'talking', 'topics', 'voice', 'brain', 'data'}

class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def text(self):
        if self.tag in {'script', 'style'} or 'hidden' in self.attrs or self.attrs.get('aria-hidden') == 'true':
            return ''
        return ' '.join(c.text() if isinstance(c, Node) else c for c in self.children)
    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(node)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break
    def handle_data(self, data):
        self.stack[-1].children.append(data)

def norm(s):
    return ' '.join(s.replace('`','').replace('**','').split())

def config_defaults():
    tree = ast.parse((APP / 'run.py').read_text())
    assignments = [n.value for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == '_CONFIG_DEFAULT' for t in n.targets)]
    if len(assignments) != 1:
        raise ValueError('expected exactly one _CONFIG_DEFAULT dictionary')
    return ast.literal_eval(assignments[0])

def verify():
    failures = []
    def require(ok, code, detail):
        if not ok:
            failures.append(f'{code}: {detail}')
    agents = (APP.parents[1] / 'AGENTS.md').read_text()
    headings = list(re.finditer(r'^(#{1,6}) (.+)$', agents, re.M))
    sections = {}
    for i, h in enumerate(headings):
        end = next((n.start() for n in headings[i+1:] if len(n[1]) <= len(h[1])), len(agents))
        sections[h[2]] = norm(agents[h.end():end])
    manifest = ROOT / 'CLAIMS.md'
    rows = []
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            if line.startswith('| ') and not line.startswith('| ID '):
                cells = [v.strip() for v in line.strip('|').split('|')]
                require(len(cells) == 5, 'manifest', line)
                if len(cells) == 5:
                    rows.append(cells)
    ids = [r[0] for r in rows]
    require(REQUIRED <= set(ids), 'manifest', f'missing claims {sorted(REQUIRED - set(ids))}')
    require(len(ids) == len(set(ids)), 'manifest', 'duplicate claim ids')
    for ident, heading, excerpt, wording, targets in rows:
        require(bool(excerpt) and norm(excerpt) in sections.get(heading, ''), 'source', ident + ': ' + heading)
        paths = [v.strip() for v in targets.split(',')]
        require(any(v.split('#')[0] in {'llms-full.txt','@web/llms-full.txt'} for v in paths), 'coverage', ident + ': no long-form target')
        for target in paths:
            file, _, anchor = target.partition('#')
            path = WEB / file[5:] if file.startswith('@web/') else ROOT / file
            if not path.exists():
                require(False, 'claim', ident + ': missing ' + target)
                continue
            txt = path.read_text()
            if path.suffix == '.html':
                page = Page(txt)
                nodes = [n for n in page.root.walk() if n.attrs.get('id') == anchor] if anchor else [page.root]
                require(len(nodes) == 1, 'anchor', ident + ': ' + target)
                txt = nodes[0].text() if len(nodes) == 1 else ''
            else:
                txt = re.sub(r'<!--.*?-->', '', txt, flags=re.S)
            require(bool(wording) and norm(wording) in norm(txt), 'claim', ident + ': ' + target)
    if (ROOT / 'llms.txt').exists():
        # Tightened after a real survivor: commented-out short entries counted.
        # Link destinations must not stand in for visible feature descriptions.
        short = re.sub(r'<!--.*?-->', '', (ROOT / 'llms.txt').read_text(), flags=re.S)
        short = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', short).lower()
        for feature in ('driver memory', 'strategy planner', 'setup advice', 'spotter', 'developer tools'):
            require(re.search(r'^- ' + re.escape(feature) + ':', short, re.M), 'short', 'llms.txt: ' + feature)
        require('not supported yet' in short, 'short', 'llms.txt: LMU boundary')
    defaults = config_defaults()
    seen = set()
    default_seen = set()
    def default_text(key):
        value = defaults[key]
        word = 'on' if value is True else 'off' if value is False else '0 (off)' if value == 0 else str(value)
        return 'Default: ' + word + '.'
    for path in sorted(list(ROOT.glob('*.html')) + list(ROOT.glob('llms*.txt'))):
        src = path.read_text()
        page = Page(src) if path.suffix == '.html' else None
        txt = norm(page.root.text() if page else src)
        keys = re.findall(r'\[setting:\s*([a-z_][a-z_0-9]*)\]', src)
        if page:
            section = None
            for node in page.root.walk():
                if node.tag == 'h2':
                    section = node.attrs.get('id')
                if 'data-default' in node.attrs:
                    key = node.attrs['data-default']
                    require(key in defaults, 'default', path.name + ': unknown ' + key)
                    if key in defaults:
                        require(norm(node.text()) == default_text(key), 'default', path.name + ': ' + key)
                    default_seen.add(key)
                if 'data-setting' in node.attrs:
                    keys += node.attrs['data-setting'].split()
                if path.name == 'customizing.html' and section in SETTING_SECTIONS and node.tag == 'li':
                    require(bool(node.attrs.get('data-setting')), 'setting', path.name + ': unregistered item ' + norm(node.text())[:90])
        if not page:
            for line in src.splitlines():
                for key in re.findall(r'\[setting:\s*([a-z_][a-z_0-9]*)\]', line):
                    if key in defaults:
                        require(default_text(key) in line, 'default', path.name + ': ' + key)
                        default_seen.add(key)
        for key in keys:
            require(key in defaults, 'setting', path.name + ': unknown ' + key)
            seen.add(key)
        # Configuration references are data, not performance claims. Examples of
        # race gaps/lap times are also allowed; benchmark and latency pitches are not.
        banned = [r'\breal[ -]time\b', r'\b(?:any|every|all) wheel(?:s| button)?\b',
                  r'\b(?:80 of 80|93[–-]94|3,500|1\.5[–-]3 seconds|third of the tokens)\b',
                  r'\b80\s*/\s*80\b', r'ko-fi\.com', r'voluntary (?:Ko-fi )?tips', r'accepts voluntary tips',
                  # ADDED 2026-10-09 by the audit: "the owner's cadence test" is the project's own vocabulary (it came from the
                  # brief). A reader of the public site has no owner; the copy tells THEM what to run.
                  r"\bowner['\u2019]s\b"]
        for pattern in banned:
            require(not re.search(pattern, txt, re.I), 'policy', path.name + ': ' + pattern)
    for key in ('driver_memory', 'spotter_mode', 'min_call_gap_s', 'max_call_words', 'dev_mode'):
        require(key in seen, 'setting', 'undocumented key ' + key)
        require(key in default_seen, 'default', 'undocumented default ' + key)
    return failures

def main():
    try:
        failures = verify()
    except Exception as exc:
        print(f'CRASH: {type(exc).__name__}: {exc}')
        return 2
    for failure in failures:
        print('FAIL ' + failure)
    print(f'{len(failures)} content failure(s)')
    return 1 if failures else 0

if __name__ == '__main__':
    sys.exit(main())
