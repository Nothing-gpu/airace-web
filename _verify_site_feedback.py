#!/usr/bin/env python3
"""Fail unless the site meets the owner's OLED / red / logo / eyebrow / socials /
motion feedback.

Requirements (site owner, verbatim): "make the webpage deepblack like oled black
make the red more saturation also idk why you changed that line in our logo to
red keep it white and add animations really express yourself ... and dont make
my git and yt large as fuck keep it subtle and remove these kinds of smaller
text above big text 'AI race engineer · ACC · F1 25'".

Checks, per page (index.html, 404.html, og-image.html where it applies):
  A. OLED: html and body computed background-color is rgb(0, 0, 0), and
     <meta name="theme-color"> is #000 / #000000.
  B. Red: the --accent custom property on :root is a saturated red:
     HSL saturation >= 95%, HSV saturation >= 85% (the old #ff5a3c is 76%),
     hue within 0..12 deg, and it is not #ff5a3c. It must reach 4.5:1
     against #000. No file may still contain the old #ff5a3c / #ff7359.
  C. Logo: every brand mark svg (the one holding the helmet path) has only
     white strokes: each channel >= 225 and max-min <= 12.
  D. Eyebrows: no element whose text matches /AI race engineer · ACC/i, and no
     "big text" is sat under a small label. Big text = h1, h2, h3, or any
     element with font-size >= 28px. A small label = a visible element with
     font-size <= 14px, text <= 60 chars, and no links/buttons inside, that is
     (a) the big element's previous element sibling, or (b) the big element's
     first child rendered as a block above the rest of the text.
     Illustrated UI (anything inside a <figure>) is exempt: its labels are
     part of the drawing.
  E. Socials: every visible link to youtube.com or github.com renders with
     font-size <= 16px (itself and every descendant) and height <= 48px.
  F. Contrast: every visible element with its own text has >= 4.5:1 contrast
     against the first opaque background behind it (>= 3:1 if >= 24px, or
     >= 18.66px bold). Decorative (aria-hidden) text is skipped.
  G. Reduced motion (reducedMotion: 'reduce'), after load: every element with
     its own text inside <main>, header and footer has effective opacity 1
     (product over ancestors) and no translate/scale offset on itself or any
     ancestor; every svg path has stroke-dashoffset 0.
  H. No JS (javaScriptEnabled: false): the same visibility rule as G.
  I. No console errors or page errors while loading with motion on, and after
     scrolling to the bottom.

Files starting with "_" are not published by GitHub Pages (Jekyll skips them).

Usage:  PW_CHROMIUM=/path/to/chrome python3 _verify_site_feedback.py
"""
import asyncio
import functools
import http.server
import os
import pathlib
import re
import sys
import threading

from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PAGES = ["index.html", "404.html"]
BASE = ""  # set in main(): pages are served over HTTP so root-absolute links (/favicon.svg) resolve
ALL = PAGES + ["og-image.html"]

COMMON_JS = r"""
window.__v = {
  rgb(s) { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null;
           const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
           return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; },
  lum(c) { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
           return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); },
  ratio(a, b) { const x = this.lum(a), y = this.lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); },
  visible(e) { const cs = getComputedStyle(e);
           if (cs.display === 'none' || cs.visibility === 'hidden') return false;
           const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; },
  ownText(e) { let t = ''; for (const n of e.childNodes) if (n.nodeType === 3) t += n.textContent;
           return t.trim(); },
  name(e) { let s = e.tagName.toLowerCase(); if (e.id) s += '#' + e.id;
           if (typeof e.className === 'string' && e.className.trim()) s += '.' + e.className.trim().split(/\s+/).join('.');
           const t = (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
           return t ? s + ' "' + t + '"' : s; },
};
"""

STATIC_PROBE = r"""
() => {
  const V = window.__v, out = [];
  // A. OLED
  for (const el of [document.documentElement, document.body]) {
    const bg = getComputedStyle(el).backgroundColor;
    if (bg !== 'rgb(0, 0, 0)') out.push(`A: ${el.tagName.toLowerCase()} background is ${bg}, want rgb(0, 0, 0)`);
  }
  const tc = document.querySelector('meta[name="theme-color"]');
  if (tc && !/^#0{3}(0{3})?$/i.test(tc.content)) out.push(`A: theme-color is ${tc.content}, want #000000`);

  // B. accent
  const acc = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
  const m = acc.match(/^#([0-9a-f]{6})$/i);
  if (!m) out.push(`B: --accent is "${acc}", want a #rrggbb red`);
  else {
    const n = parseInt(m[1], 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    const mx = Math.max(r, g, b) / 255, mn = Math.min(r, g, b) / 255, l = (mx + mn) / 2;
    const sHsl = mx === mn ? 0 : (mx - mn) / (1 - Math.abs(2 * l - 1));
    const sHsv = mx === 0 ? 0 : (mx - mn) / mx;
    let h = 0; if (mx !== mn && r / 255 === mx) h = (60 * (((g - b) / 255) / (mx - mn)) + 360) % 360;
    if (acc.toLowerCase() === '#ff5a3c') out.push('B: --accent is still #ff5a3c');
    if (sHsl < 0.95) out.push(`B: --accent ${acc} HSL saturation ${(sHsl * 100).toFixed(1)}% < 95%`);
    if (sHsv < 0.85) out.push(`B: --accent ${acc} HSV saturation ${(sHsv * 100).toFixed(1)}% < 85% (old #ff5a3c = 76%)`);
    if (!(h <= 12 || h >= 355)) out.push(`B: --accent ${acc} hue ${h.toFixed(1)} is not a red`);
    const cr = V.ratio({r, g, b}, {r: 0, g: 0, b: 0});
    if (cr < 4.5) out.push(`B: --accent ${acc} contrast on #000 ${cr.toFixed(2)} < 4.5`);
  }

  // C. logo strokes
  document.querySelectorAll('svg').forEach((svg, i) => {
    if (!svg.querySelector('path[d^="M146,410"]')) return;
    svg.querySelectorAll('path').forEach((p, j) => {
      const s = getComputedStyle(p).stroke; const c = V.rgb(s);
      if (!c) { out.push(`C: brand svg #${i} path ${j} stroke "${s}"`); return; }
      const ok = Math.min(c.r, c.g, c.b) >= 225 && Math.max(c.r, c.g, c.b) - Math.min(c.r, c.g, c.b) <= 12;
      if (!ok) out.push(`C: brand svg #${i} path ${j} stroke ${s} is not white`);
    });
  });

  // D. eyebrows
  if (/AI race engineer\s*·\s*ACC/i.test(document.body.innerText))
    out.push('D: text "AI race engineer · ACC" is still on the page');
  const small = (e) => {
    if (!e || !V.visible(e)) return false;
    const cs = getComputedStyle(e);
    const t = (e.innerText || '').trim();
    return parseFloat(cs.fontSize) <= 14 && t.length > 0 && t.length <= 60 && !e.querySelector('a,button') && !e.matches('a,button');
  };
  for (const e of document.body.querySelectorAll('*')) {
    if (e.closest('figure') || e.closest('svg') || !V.visible(e)) continue;
    const big = e.matches('h1,h2,h3') || parseFloat(getComputedStyle(e).fontSize) >= 28;
    if (!big || !(e.innerText || '').trim()) continue;
    const prev = e.previousElementSibling;
    if (small(prev)) out.push(`D: small label ${V.name(prev)} sits above big text ${V.name(e)}`);
    const fc = e.firstElementChild;
    if (fc && small(fc) && getComputedStyle(fc).display !== 'inline') {
      // a first child only counts if it is rendered as its own line on top of the rest
      const fr = fc.getBoundingClientRect(), er = e.getBoundingClientRect();
      if (Math.abs(fr.top - er.top) < 2 && er.height > fr.height * 1.5)
        out.push(`D: small label ${V.name(fc)} sits on top inside big text ${V.name(e)}`);
    }
  }

  // E. socials
  document.querySelectorAll('a[href*="youtube.com"], a[href*="github.com"]').forEach(a => {
    if (!V.visible(a)) return;
    let fs = parseFloat(getComputedStyle(a).fontSize);
    a.querySelectorAll('*').forEach(d => { if (V.visible(d)) fs = Math.max(fs, parseFloat(getComputedStyle(d).fontSize)); });
    const h = a.getBoundingClientRect().height;
    if (fs > 16.01) out.push(`E: social link ${V.name(a)} font-size ${fs}px > 16px`);
    if (h > 48.5) out.push(`E: social link ${V.name(a)} height ${Math.round(h)}px > 48px`);
  });

  // F. contrast
  const bgOf = (e) => {
    for (let n = e; n; n = n.parentElement) {
      const c = V.rgb(getComputedStyle(n).backgroundColor);
      if (c && c.a >= 0.99) return c;
    }
    return {r: 0, g: 0, b: 0};
  };
  for (const e of document.body.querySelectorAll('*')) {
    if (e.closest('svg') || e.closest('[aria-hidden="true"]') || !V.visible(e) || !V.ownText(e)) continue;
    if (e.classList.contains('skip')) continue;
    const cs = getComputedStyle(e);
    const fg = V.rgb(cs.color); if (!fg) continue;
    const r = V.ratio(fg, bgOf(e));
    const fs = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (fs >= 24 || (bold && fs >= 18.66)) ? 3 : 4.5;
    if (r < need - 0.01) out.push(`F: contrast ${r.toFixed(2)} < ${need} (${cs.color} on bg) ${V.name(e)}`);
  }
  return out;
}
"""

VISIBILITY_PROBE = r"""
() => {
  const V = window.__v, out = [];
  const roots = document.querySelectorAll('main, header, footer, body > .wrap');
  const seen = new Set();
  for (const root of roots) for (const e of root.querySelectorAll('*')) {
    if (seen.has(e)) continue; seen.add(e);
    if (e.closest('svg') || e.closest('details:not([open]) > :not(summary)')) continue;
    if (!V.ownText(e)) continue;
    const cs0 = getComputedStyle(e);
    if (cs0.display === 'none') continue;
    if (e.closest('.nav-links') && getComputedStyle(e.closest('.nav-links')).display === 'none') continue;
    let op = 1, moved = null;
    for (let n = e; n && n !== document.documentElement; n = n.parentElement) {
      const cs = getComputedStyle(n);
      op *= parseFloat(cs.opacity);
      if (cs.visibility === 'hidden') op = 0;
      const t = cs.transform;
      if (t && t !== 'none') {
        const mm = new DOMMatrixReadOnly(t);
        if (Math.abs(mm.m41) > 0.5 || Math.abs(mm.m42) > 0.5 || Math.abs(mm.a - 1) > 0.01 || Math.abs(mm.d - 1) > 0.01)
          moved = moved || `${V.name(n)} has transform ${t}`;
      }
      const cp = cs.clipPath;
      if (cp && cp !== 'none' && /inset\([^)]*100%/.test(cp)) moved = moved || `${V.name(n)} clip-path ${cp}`;
    }
    if (op < 0.999) out.push(`hidden: effective opacity ${op.toFixed(2)}: ${V.name(e)}`);
    if (moved) out.push(`offset: ${V.name(e)} <- ${moved}`);
  }
  document.querySelectorAll('svg path').forEach(p => {
    const d = parseFloat(getComputedStyle(p).strokeDashoffset || '0');
    if (Math.abs(d) > 0.5) out.push(`undrawn svg path (stroke-dashoffset ${d}) in ${V.name(p.closest('svg').parentElement)}`);
  });
  return out;
}
"""


def static_file_checks():
    out = []
    for f in ALL:
        txt = (ROOT / f).read_text(encoding="utf-8")
        for old in ("#ff5a3c", "#ff7359", "255,90,60", "255, 90, 60"):
            if old.lower() in txt.lower():
                out.append(f"B: {f} still contains old red {old}")
    return out


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


async def load(ctx, name, errors):
    pg = await ctx.new_page()
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    await pg.add_init_script(COMMON_JS)
    await pg.goto(BASE + name, wait_until="networkidle")
    await pg.evaluate("document.fonts.ready.then(() => true)")
    return pg


async def main():
    global BASE
    handler = functools.partial(QuietHandler, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    BASE = f"http://127.0.0.1:{srv.server_address[1]}/"
    results = {}

    def report(key, problems):
        results[key] = problems
        print(("FAIL " if problems else "ok   ") + key + (f": {len(problems)}" if problems else ""))
        for p in problems[:30]:
            print("   -", p)
        if len(problems) > 30:
            print(f"   ... and {len(problems) - 30} more")

    report("static files: no old red", static_file_checks())

    async with async_playwright() as p:
        kw = {"args": ["--ignore-certificate-errors"]}
        if os.environ.get("PW_CHROMIUM"):
            kw["executable_path"] = os.environ["PW_CHROMIUM"]
        browser = await p.chromium.launch(**kw)

        for name in ALL:
            for w in ([390, 1440] if name != "og-image.html" else [1200]):
                ctx = await browser.new_context(viewport={"width": w, "height": 900 if w != 1200 else 630},
                                                reduced_motion="reduce", ignore_https_errors=True)
                errs = []
                pg = await load(ctx, name, errs)
                probs = await pg.evaluate(STATIC_PROBE)
                if name == "og-image.html":
                    # og-image is a picture: only the colour, logo and eyebrow rules apply
                    probs = [x for x in probs if x[:2] in ("B:", "C:", "D:")]
                    bg = await pg.evaluate("getComputedStyle(document.body).backgroundColor")
                    if bg != "rgb(0, 0, 0)":
                        probs.append(f"A: og-image body background {bg}")
                report(f"{name} @ {w}px requirements (A-F)", probs)
                if name != "og-image.html":
                    report(f"{name} @ {w}px reduced motion: all content visible (G)", await pg.evaluate(VISIBILITY_PROBE))
                await ctx.close()

        for name in PAGES:
            ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, java_script_enabled=False,
                                            ignore_https_errors=True)
            pg = await ctx.new_page()
            await pg.goto(BASE + name, wait_until="networkidle")
            # the page's own scripts are off; Playwright's evaluate still runs, so inject the helpers inline
            probe = "() => { " + COMMON_JS + " return (" + VISIBILITY_PROBE + ")(); }"
            report(f"{name} no JS: all content visible (H)", await pg.evaluate(probe))
            await ctx.close()

            for w in (390, 1440):
                ctx = await browser.new_context(viewport={"width": w, "height": 900}, ignore_https_errors=True)
                errs = []
                pg = await load(ctx, name, errs)
                await pg.evaluate("""async () => {
                  for (let y = 0; y < document.body.scrollHeight; y += 400) { window.scrollTo({top: y, behavior: 'instant'}); await new Promise(r => setTimeout(r, 120)); }
                }""")
                await pg.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
                await pg.wait_for_timeout(4000)
                report(f"{name} @ {w}px motion on: no console errors (I)", errs)
                report(f"{name} @ {w}px motion on, settled: all content visible", await pg.evaluate(VISIBILITY_PROBE))
                await ctx.close()
        await browser.close()

    bad = sum(len(v) for v in results.values())
    print(f"\n{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
