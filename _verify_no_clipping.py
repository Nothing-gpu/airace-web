#!/usr/bin/env python3
"""Fail if anything on the site clips or overflows.

Requirement (from the site owner): nothing may clip or overflow -- button
labels, nav items, cards, headings, code blocks, pills -- at 360, 390, 768,
1280, 1440 and 1920 px, and there must be no horizontal page scroll.

For every page at every width this checks, with fonts loaded:
  1. document.documentElement.scrollWidth > innerWidth  (horizontal page scroll)
  2. any visible element whose scrollWidth > clientWidth + 1, unless it is
     intentionally scrollable (overflow-x: auto/scroll)
  3. any visible element that sticks out horizontally past its nearest
     non-scrolling ancestor box, or past the parent that clips it (overflow
     hidden/clip) on either axis
  4. any element with text-overflow: ellipsis that is actually truncating

It runs twice per width: once as loaded, and once with every <details> open
and the mobile menu open, so collapsed content is checked too.

Vertical overflow of a non-clipping parent is not counted: inline glyph boxes
in tight display type (line-height < 1) always extend past their line box
without anything being cut off. Vertical overflow into a parent that clips
(overflow hidden/clip) IS counted, because that is where text gets cut.

Files starting with "_" are not published by GitHub Pages (Jekyll skips them).

Usage:  python3 _verify_no_clipping.py            (exit 1 on any failure)
Needs:  pip install playwright; a Chromium build (PW_CHROMIUM env var, or
        Playwright's own).
"""
import asyncio
import os
import pathlib
import sys

from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent
PAGES = ["index.html", "404.html"]
WIDTHS = [360, 390, 768, 1280, 1440, 1920]

PROBE = r"""
() => {
  const W = window.innerWidth;
  const out = [];
  const name = (e) => {
    let s = e.tagName.toLowerCase();
    if (e.id) s += '#' + e.id;
    if (typeof e.className === 'string' && e.className.trim())
      s += '.' + e.className.trim().split(/\s+/).join('.');
    const t = (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return t ? s + ' "' + t + '"' : s;
  };
  const visible = (e) => {
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const scrollsX = (cs) => cs.overflowX === 'auto' || cs.overflowX === 'scroll';
  const clips = (cs) => ['hidden', 'clip'].includes(cs.overflowX) || ['hidden', 'clip'].includes(cs.overflowY);

  if (document.documentElement.scrollWidth > W)
    out.push(`page scrolls sideways: scrollWidth ${document.documentElement.scrollWidth} > ${W}`);

  for (const e of document.body.querySelectorAll('*')) {
    if (e.closest('svg') && e.tagName.toLowerCase() !== 'svg') continue;  // svg internals
    if (!visible(e)) continue;
    const cs = getComputedStyle(e);
    // skip-link is parked off-screen on purpose until focused
    if (e.classList.contains('skip')) continue;

    // 2. content wider than the box
    if (e.clientWidth > 0 && e.scrollWidth > e.clientWidth + 1 && !scrollsX(cs) && cs.display !== 'inline')
      out.push(`overflows its own box (${e.scrollWidth} > ${e.clientWidth}): ${name(e)}`);

    // 4. ellipsis actually truncating
    if (cs.textOverflow === 'ellipsis' && e.scrollWidth > e.clientWidth + 1)
      out.push(`ellipsis truncating: ${name(e)}`);

    // 3. sticking out of an ancestor
    const r = e.getBoundingClientRect();
    if (r.right > W + 1 || r.left < -1)
      out.push(`outside the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${W}): ${name(e)}`);
    const p = e.parentElement;
    if (p && p !== document.body && cs.position !== 'fixed') {
      const pcs = getComputedStyle(p);
      if (!scrollsX(pcs) && pcs.display !== 'inline' && pcs.display !== 'contents') {
        const pr = p.getBoundingClientRect();
        const horiz = r.left < pr.left - 1 || r.right > pr.right + 1;
        const vert = r.top < pr.top - 1 || r.bottom > pr.bottom + 1;
        if (horiz || (vert && clips(pcs)))
          out.push(`sticks out of ${name(p).split(' ')[0]} (${Math.round(r.left)}..${Math.round(r.right)} vs ${Math.round(pr.left)}..${Math.round(pr.right)}${vert && clips(pcs) ? ', clipped vertically' : ''}): ${name(e)}`);
      }
    }
  }
  return out;
}
"""

EXPAND = """
() => {
  document.querySelectorAll('details').forEach(d => d.open = true);
  const b = document.querySelector('.menu-btn');
  if (b && getComputedStyle(b).display !== 'none' && b.getAttribute('aria-expanded') !== 'true') b.click();
}
"""


async def main():
    failures = 0
    async with async_playwright() as p:
        kw = {"args": ["--ignore-certificate-errors"]}
        exe = os.environ.get("PW_CHROMIUM")
        if exe:
            kw["executable_path"] = exe
        browser = await p.chromium.launch(**kw)
        for page_name in PAGES:
            for w in WIDTHS:
                ctx = await browser.new_context(viewport={"width": w, "height": 900},
                                                ignore_https_errors=True,
                                                reduced_motion="reduce")
                pg = await ctx.new_page()
                await pg.goto((ROOT / page_name).as_uri(), wait_until="networkidle")
                await pg.evaluate("document.fonts.ready.then(() => true)")
                fonts = await pg.evaluate(
                    "document.fonts.check('700 20px \"Barlow Condensed\"') && document.fonts.check('500 14px \"JetBrains Mono\"')")
                for state in ("as loaded", "expanded"):
                    if state == "expanded":
                        await pg.evaluate(EXPAND)
                        await pg.wait_for_timeout(100)
                    problems = await pg.evaluate(PROBE)
                    tag = f"{page_name} @ {w}px ({state}{'' if fonts else ', WEB FONTS NOT LOADED'})"
                    if problems:
                        failures += len(problems)
                        print(f"FAIL {tag}: {len(problems)}")
                        for pr in problems[:40]:
                            print("   -", pr)
                        if len(problems) > 40:
                            print(f"   ... and {len(problems) - 40} more")
                    else:
                        print(f"ok   {tag}")
                await ctx.close()
        await browser.close()
    print(f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
