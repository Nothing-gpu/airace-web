#!/usr/bin/env python3
"""Legal and discoverability check for airacegp.com. WRITTEN BEFORE THE FIXES.

Owner decisions this encodes (2026-10-03): airaceGP is free forever and never
sold (Ko-fi tips only), so there is no seller imprint and no personal details
anywhere; no full privacy policy, a short privacy note instead; the site
follows the Luxembourg accessibility rules voluntarily, as the owner asked.

  1 PRIVACY   No page makes a request to another site: no Google Fonts (they
              send every visitor's IP to Google), no third-party script, style,
              image or frame. Fonts are self-hosted with their OFL licences.
              Every page's footer says there are no cookies or analytics and
              links GitHub's privacy statement (the host keeps server logs).
  2 A11Y STMT The accessibility statement names the standard (EN 301 549,
              WCAG 2.1 AA), says why the law does not oblige a free private
              project (Czech Acts 99/2019 and 424/2023; the Luxembourg rules
              followed voluntarily), does not say "fully compliant" while no
              screen-reader test has been done, no longer says the fonts come
              from Google, and offers an email contact besides GitHub.
  3 WCAG      Outline controls (.btn, .motion-btn, .menu-btn) have borders of
              at least 3:1 against the page (1.4.11); the credits sit under
              their own h2 (1.3.1); the Japanese name is marked lang="ja"
              (3.1.2); og-image.html is kept out of search (noindex).
  4 MARKS     Every page carries the full non-affiliation notice plus a
              catch-all for every other brand named on the site.
  5 HONEST    No personal-data placeholders, no price or paid tier: the site
              says it is free; schema.org price stays 0.
  6 AGENTS    /llms.txt (llmstxt.org format) and /llms-full.txt exist, are
              linked from the page head, describe every feature, and
              robots.txt welcomes AI crawlers and points at both and the sitemap.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = ['index.html', 'accessibility.html', '404.html', 'og-image.html']
fails = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f'  ({detail})' if detail else ''))
    if not ok:
        fails.append(name)


def read(p):
    path = os.path.join(HERE, p)
    return open(path, encoding='utf-8').read() if os.path.exists(path) else ''


html = {p: read(p) for p in PAGES}

# 1 ─ privacy
for p, s in html.items():
    third = re.findall(r'<(?:link|script|img|iframe|source|video|audio)\b[^>]*\b(?:href|src)="(https?://[^"]+)"', s)
    third += re.findall(r'@import\s+url\(["\']?(https?://[^)"\']+)', s)
    third += re.findall(r'url\(["\']?(https?://[^)"\']+)', s)
    third = [u for u in third if not re.match(r'https?://(www\.)?(docs\.)?airacegp\.com/', u)]
    check(f'1a {p}: no request to another site', not third, str(third[:3]))
for f in ('barlow-400.woff2', 'barlow-condensed-700.woff2', 'jetbrains-mono.woff2', 'OFL-Barlow.txt', 'OFL-JetBrainsMono.txt'):
    check(f'1b fonts/{f} self-hosted', os.path.exists(os.path.join(HERE, 'fonts', f)))
for p in ('index.html', 'accessibility.html', '404.html'):
    foot = html[p][html[p].rfind('<footer'):]
    check(f'1c {p}: footer privacy note', re.search(r'no cookies', foot, re.I) and re.search(r'no analytics', foot, re.I)
          and 'docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement' in foot)

# 2 ─ accessibility statement
a = html['accessibility.html']
check('2a names EN 301 549 and WCAG 2.1 AA', 'EN 301 549' in a and 'WCAG 2.1' in a)
check('2b explains Czech law and the voluntary Luxembourg standard',
      '99/2019' in a and '424/2023' in a and 'Luxembourg' in a and 'voluntar' in a)
check('2c no "fully compliant" before a screen-reader test', not re.search(r'fully compliant', a, re.I)
      and re.search(r'partially compliant', a, re.I))
check('2d no longer says the fonts come from Google', 'Google Fonts' not in a)
check('2e email contact besides GitHub', 'mailto:contact@airacegp.com' in a)

# 3 ─ WCAG fixes


def lum(rgb):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (c(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def colour(css, value, bg):
    m = re.match(r'var\((--[\w-]+)\)', value.strip())
    if m:
        d = re.search(re.escape(m.group(1)) + r'\s*:\s*([^;]+);', css)
        value = d.group(1) if d else ''
    m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\)', value.strip())
    if m:
        rgb, al = [int(m.group(i)) for i in (1, 2, 3)], float(m.group(4) or 1)
        return [round(al * c + (1 - al) * b) for c, b in zip(rgb, bg)]
    m = re.match(r'#([0-9a-fA-F]{6})', value.strip())
    return [int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)] if m else None


for p in ('index.html', '404.html'):
    css = html[p]
    for sel in ('.btn', '.motion-btn', '.menu-btn'):
        rule = re.search(r'(?:^|[}\s,])' + re.escape(sel) + r'\s*\{([^}]*)\}', css)
        if not rule:
            if sel == '.btn' or p == 'index.html':
                check(f'3a {p} {sel} rule found', False)
            continue
        bd = re.search(r'border(?:-color)?\s*:\s*(?:\d+px\s+\w+\s+)?([^;]+);', rule.group(1))
        worst = None
        for bg in ([0, 0, 0], [0x16, 0x16, 0x16]):
            c = colour(css, bd.group(1), bg) if bd else None
            r = ratio(c, bg) if c else 0
            worst = r if worst is None else min(worst, r)
        check(f'3a {p} {sel} border >= 3:1', worst >= 3, f'{worst:.2f}:1')
i = html['index.html']
cred = i[i.find('id="credits"') - 300:i.find('id="credits"') + 1500] if 'id="credits"' in i else ''
check('3b credits have their own h2', re.search(r'<h2\b[^>]*>[^<]*Credits', cred) is not None)
check('3c Japanese name marked lang="ja"', '<span lang="ja">ごひょううぺこ</span>' in i)
check('3d og-image.html noindex', 'name="robots" content="noindex' in html['og-image.html'])

# 4 ─ marks
for p in ('index.html', 'accessibility.html', '404.html'):
    s = html[p]
    check(f'4a {p}: full non-affiliation notice',
          all(k in s for k in ('Formula One Licensing BV', 'trademarks of Formula One Licensing BV',
                               'Kunos Simulazioni, published by 505 Games', 'Electronic Arts Inc. and Codemasters')))
    check(f'4b {p}: catch-all for other brands', 'property of their respective owners' in s)

# 5 ─ honest
for p, s in html.items():
    check(f'5a {p}: no owner placeholders', not re.search(r'OWNER INPUT|TODO\(owner\)', s))
check('5b says free, forever', re.search(r'free,? forever', i, re.I) is not None)
check('5c schema.org price 0', re.search(r'"price":\s*"0"', i) is not None)
check('5d no paid tier or price claims', not re.search(r'(?i)\b(premium|pro plan|per month|/month|subscribe now)\b', i))

# 6 ─ agents
llms = read('llms.txt')
full = read('llms-full.txt')
check('6a llms.txt: H1, summary blockquote, H2 link sections',
      llms.startswith('# airaceGP') and re.search(r'^> .+', llms, re.M) and re.search(r'^## .+\n+- \[.+\]\(https?://', llms, re.M))
FEATURES = ['Assetto Corsa Competizione', 'F1 25', 'push to talk', 'wheel', 'voice detection', 'wake word',
            'nine languages', 'offline', 'model chain', 'fallback', 'Ollama', 'Groq', 'Gemini', 'OpenRouter',
            'Anthropic', 'OpenAI-compatible', 'error code', 'fuel', 'pressure', 'gap', 'lapped', 'damage',
            'weather', 'pit', 'live timing', 'analysis', 'corner', 'phone', 'chattiness', 'call length',
            'custom instructions', 'Piper', 'male', 'free', 'Ko-fi', 'Windows', 'faster-whisper', 'privacy',
            'quiet', 'drink', 'SimHub']
for name, txt in (('llms.txt', llms), ('llms-full.txt', full)):
    miss = [f for f in FEATURES if f.lower() not in txt.lower()]
    check(f'6b {name} covers every feature', not miss, f'missing {miss}')
check('6c llms-full.txt is the long form', len(full) > 2.5 * max(1, len(llms)), f'{len(full)} vs {len(llms)} chars')
check('6d linked from the page head', 'rel="alternate" type="text/markdown" href="/llms.txt"' in i)
robots = read('robots.txt')
check('6e robots.txt welcomes AI crawlers and lists llms + sitemap',
      all(b in robots for b in ('GPTBot', 'ClaudeBot', 'PerplexityBot', 'Google-Extended'))
      and 'Disallow: /\n' not in robots and 'Sitemap: https://airacegp.com/sitemap.xml' in robots and 'llms.txt' in robots)
check('6f sitemap.xml lists the pages', all(u in read('sitemap.xml') for u in
                                            ('https://airacegp.com/', 'https://airacegp.com/accessibility.html',
                                             'https://airacegp.com/llms.txt')))

print(f'\n{"ALL PASS" if not fails else f"{len(fails)} FAILED"}')
sys.exit(1 if fails else 0)
