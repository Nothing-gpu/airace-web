#!/usr/bin/env python3
"""Accessibility check: WCAG 2.1 Level AA (EN 301 549 V3.2.1, clause 9), the
bar the Luxembourg digital-accessibility framework (RAAM) sets for websites.
WRITTEN BEFORE THE FIXES, from the requirement, and watched failing first.

Every published page is driven with Playwright at 390 px and 1440 px, once with
motion allowed and once with prefers-reduced-motion: reduce. Per run:

  AXE   axe-core, tags wcag2a wcag2aa wcag21a wcag21aa: zero violations.
        Results axe cannot decide ("incomplete") are printed as REVIEW lines
        for a human; they are listed, never silently ignored.
  KBD   Tab through the whole page. Every interactive element is reached, in
        DOM order (no positive tabindex, no CSS order/reverse on the way), and
        focus returns to the browser after the last one (no trap). Each focus
        stop is visible (not transparent, not covered by e.g. the sticky
        header) and has an indicator measured in PIXELS: the area whose colour
        changes by >= 3:1 between unfocused and focused must be at least a
        2 CSS px ring around the element's visible sides (so an outline that
        is clipped away does not count). The skip link is the first stop, is
        on screen when focused, and moves focus into <main>. The mobile menu
        opens with Enter and Space, Tab enters it, leaving it does not leave
        focus hidden under it, Escape closes it and returns focus to its
        button. Every <details> opens and closes with Enter and Space.
  2.2.2 Pause, Stop, Hide. The page is scrolled screen by screen; wherever
        something is still animating or being changed by script 5 s after
        arriving, there must be a visible, keyboard-operable pause control
        (a button[aria-pressed] named "Pause animations"). Pressing it with
        the keyboard must stop ALL motion (no running animation, no DOM
        change for 2 s) with every piece of text fully visible, survive a
        reload (localStorage), and still work when localStorage throws.
        Also (motion on, 1440 px): no CSS animation repeats forever, and every
        loop has stopped by itself 20 s after its section came into view.
  2.3.1 No flashing: every CSS animation of opacity/colour met on the page is
        replayed off-screen in 10 ms steps and its luminance counted the way
        WCAG defines a flash (opposing changes of >= 0.1 relative luminance
        with the darker state < 0.8); more than 3 flashes in any 1 s fails.
        Script-driven class/style toggling faster than 6 per second fails too.
  1.4.3 / 1.4.11  Text contrast >= 4.5:1 (>= 3:1 for large text) against the
        first opaque background; every interactive element is identified by
        text that passes, or by an icon/border with >= 3:1.
  BASE  lang set; <title> unique and descriptive; header, labelled nav(s) with
        distinct labels, one main, footer; exactly one h1, no skipped heading
        levels; every link has a name that is not generic ("here", "more"),
        one name never points to two different places, an aria-label contains
        the visible text; links that open a new tab say so; every svg is
        aria-hidden or a named image; every img has alt; role=img has a name;
        the hero illustration's text alternative carries its point.
  STMT  accessibility.html exists and is linked from the footer of every page;
        it states a compliance status against WCAG 2.1 AA / EN 301 549
        V3.2.1, the date and method, the GitHub issues route with a one-month
        answer, says the project is private and voluntary, invents no email,
        keeps the owner TODO, and never mentions the public-sector referral.
Layout, per page and motion mode:
  1.4.10 at 320 x 640: no sideways scroll, nothing clipped (the clipping
        measure from _verify_no_clipping.py).
  1.4.4 200% zoom = a 1440 x 900 window at 720 x 450 CSS px: same, and the
        sticky header takes at most a third of the height.
  1.4.12 with the WCAG text-spacing styles injected (line-height 1.5,
        paragraph spacing 2em, letter-spacing .12em, word-spacing .16em) at
        390 and 1440: nothing clipped, no two pieces of text overlapping.

axe-core: AXE_JS=/path/to/axe.min.js, else a cached copy of the pinned version
(~/.cache/airace-a11y), fetched from cdn.jsdelivr.net or, failing that, npm.
Chromium: PW_CHROMIUM, else /opt/pw-browsers/.../chrome when it exists, else
Playwright's own. Files starting with "_" are not published by GitHub Pages.

    python3 _verify_a11y.py                 # everything, exit 1 on a failure
    python3 _verify_a11y.py index.html      # just these pages
"""
from __future__ import annotations

import io
import json
import os
import re
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from PIL import Image

# ───────────────────────────── site config ──────────────────────────────
ROOT = Path(__file__).resolve().parent
SITE_NAME = "airaceGP"
# Published pages. og-image.html is left out on purpose: it is the source the
# social-preview PNG is rendered from, not a page anyone navigates to.
PAGES = ["index.html", "404.html", "accessibility.html"]
REDIRECT_STUBS: list[str] = []          # meta-refresh stubs: only lang/title/redirect checked
STATEMENT = "accessibility.html"
ISSUES_URL = "https://github.com/Nothing-gpu/airace-web/issues/new"
# selector -> words its text alternative must carry
MENU_PAGES = {"index.html"}             # pages whose nav collapses into a menu button below 981 px
ILLUSTRATIONS = {"index.html": {".pw": ["illustration", "McLaren", "1.4", "closing", "fuel", "pressure"]}}
# ─────────────────────────────────────────────────────────────────────────

AXE_VERSION = "4.10.3"
# A11Y_WIDTHS / A11Y_MOTIONS narrow a run while debugging; the full matrix is the check.
WIDTHS = tuple(int(x) for x in os.environ.get("A11Y_WIDTHS", "390,1440").split(","))
MOTIONS = tuple(os.environ.get("A11Y_MOTIONS", "no-preference,reduce").split(","))
CHROME = os.environ.get("PW_CHROMIUM") or os.environ.get("PW_CHROME") or "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
TEXT_SPACING_CSS = ("*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important}"
                    "p{margin-bottom:2em!important}")
FREEZE_CSS = ("*,*::before,*::after{transition:none!important;animation-play-state:paused!important}"
              "html{scroll-behavior:auto!important}")


def axe_source() -> str:
    if os.environ.get("AXE_JS"):
        return Path(os.environ["AXE_JS"]).read_text(encoding="utf-8")
    cache = Path.home() / ".cache" / "airace-a11y" / f"axe-core-{AXE_VERSION}.min.js"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
            url = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
            with urllib.request.urlopen(url, context=ctx, timeout=60) as r:
                data = r.read()
        except Exception:
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(["npm", "pack", f"axe-core@{AXE_VERSION}", "--silent"], cwd=td, check=True,
                               capture_output=True)
                tgz = next(Path(td).glob("axe-core-*.tgz"))
                with tarfile.open(tgz) as tf:
                    data = tf.extractfile("package/axe.min.js").read()
        if b"axe" not in data[:2000]:
            raise RuntimeError("downloaded axe-core does not look like axe-core")
        cache.write_bytes(data)
    return cache.read_text(encoding="utf-8")


class PagesHandler(SimpleHTTPRequestHandler):
    """GitHub Pages' lookup: /x -> x.html, /dir/ -> dir/index.html, _files unpublished, else 404.html."""

    def log_message(self, *_):
        pass

    def send_head(self):
        rel = unquote(urlparse(self.path).path).lstrip("/")
        if rel.startswith("_") or "/_" in rel:
            return self._not_found()
        target = ROOT / rel
        if target.is_dir():
            target = target / "index.html"
        elif not target.exists() and (ROOT / (rel + ".html")).exists():
            target = ROOT / (rel + ".html")
        if not target.exists():
            return self._not_found()
        self.path = "/" + str(target.relative_to(ROOT))
        return super().send_head()

    def _not_found(self):
        body = (ROOT / "404.html").read_bytes() if (ROOT / "404.html").exists() else b"404"
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)


# ─────────────────────────── in-page helpers ────────────────────────────
HELPERS = r"""
(() => {
const A = window.__a11y = {};
A.rgb = s => { const m = (s || '').match(/rgba?\(([^)]+)\)/); if (!m) return null;
  const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat);
  return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
A.lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
A.ratio = (a, b) => { const x = A.lum(a), y = A.lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
A.blend = (c, bg, k) => ({r: c.r * k + bg.r * (1 - k), g: c.g * k + bg.g * (1 - k), b: c.b * k + bg.b * (1 - k), a: 1});
A.visible = e => { const cs = getComputedStyle(e);
  if (cs.display === 'none' || cs.visibility !== 'visible') return false;
  // content of a closed <details> keeps its boxes but is not rendered (content-visibility)
  if (e.checkVisibility && !e.checkVisibility({contentVisibilityAuto: true})) return false;
  const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
A.ownText = e => { let t = ''; for (const n of e.childNodes) if (n.nodeType === 3) t += n.textContent; return t.trim(); };
A.name = e => { if (!e || !e.tagName) return String(e); let s = e.tagName.toLowerCase(); if (e.id) s += '#' + e.id;
  if (typeof e.className === 'string' && e.className.trim()) s += '.' + e.className.trim().split(/\s+/).join('.');
  const t = (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 36); return t ? s + ' "' + t + '"' : s; };
A.bgOf = e => { let layers = [];
  for (let n = e; n; n = n.parentElement) { const c = A.rgb(getComputedStyle(n).backgroundColor);
    if (c && c.a > 0) { layers.push(c); if (c.a >= 0.99) break; } }
  let bg = {r: 0, g: 0, b: 0, a: 1};
  for (let i = layers.length - 1; i >= 0; i--) bg = A.blend(layers[i], bg, layers[i].a);
  return bg; };
A.opacity = e => { let o = 1; for (let n = e; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity); return o; };
A.accName = e => {
  const lb = e.getAttribute('aria-labelledby');
  if (lb) return lb.split(/\s+/).map(i => { const x = document.getElementById(i); return x ? x.textContent : ''; }).join(' ').trim();
  const al = e.getAttribute('aria-label'); if (al && al.trim()) return al.trim();
  let t = '';
  const walk = n => { if (n.nodeType === 3) { t += n.textContent; return; }
    if (n.nodeType !== 1) return; if (n.getAttribute('aria-hidden') === 'true') return;
    const cs = getComputedStyle(n); if (cs.display === 'none' || cs.visibility === 'hidden') return;
    if (n.tagName === 'IMG') { t += ' ' + (n.getAttribute('alt') || '') + ' '; return; }
    if (n.tagName.toLowerCase() === 'svg') { const ti = n.querySelector('title'); t += ti ? ti.textContent : (n.getAttribute('aria-label') || ''); return; }
    for (const c of n.childNodes) walk(c);
    if (cs.display !== 'inline') t += ' '; };
  walk(e); t = t.replace(/\s+/g, ' ').trim();
  return t || (e.getAttribute('title') || '').trim(); };
let seq = 0;
A.tag = e => { if (!e.dataset.a11yK) e.dataset.a11yK = String(++seq); return e.dataset.a11yK; };
A.domIndex = e => Array.prototype.indexOf.call(document.getElementsByTagName('*'), e);

// ---------- motion observation ----------
A.describeAnim = a => { const t = a.effect && a.effect.target;
  const kind = a.animationName ? '@' + a.animationName : (a.transitionProperty ? 'transition ' + a.transitionProperty : 'animation');
  return kind + ' on ' + A.name(t) + (a.effect && a.effect.pseudoElement ? a.effect.pseudoElement : ''); };
A.seenAnims = new Map();
A.allAnims = new Set();
A.grab = () => { if (document.getAnimations) document.getAnimations().forEach(a => A.allAnims.add(a)); };
document.addEventListener('animationstart', A.grab, true);
document.addEventListener('transitionstart', A.grab, true);
setInterval(A.grab, 50);
A.toggles = new Map();       // element -> [timestamps] of class/style changes
A.observe = ms => new Promise(res => {
  const muts = new Map();
  const mo = new MutationObserver(list => { const now = performance.now();
    for (const m of list) { const t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
      if (!t || t.closest('[data-a11y-ignore]')) continue;
      if (m.type === 'attributes' && m.attributeName && m.attributeName.startsWith('data-a11y')) continue;
      const k = A.name(t).slice(0, 70) + ' [' + m.type + (m.attributeName ? ':' + m.attributeName : '') + ']';
      muts.set(k, (muts.get(k) || 0) + 1);
      if (m.type === 'attributes' && (m.attributeName === 'class' || m.attributeName === 'style')) {
        if (!A.toggles.has(t)) A.toggles.set(t, []); A.toggles.get(t).push(now); } } });
  mo.observe(document.documentElement, {subtree: true, attributes: true, characterData: true, childList: true});
  const running = new Set();
  const sample = () => document.getAnimations().forEach(a => {
    if (!A.seenAnims.has(a)) A.seenAnims.set(a, {desc: A.describeAnim(a), iterations: a.effect ? a.effect.getComputedTiming().iterations : 1});
    if (a.playState === 'running') running.add(A.describeAnim(a)); });
  sample(); const iv = setInterval(sample, 100);
  setTimeout(() => { clearInterval(iv); sample(); mo.disconnect();
    res({muts: [...muts].map(([k, v]) => k + ' x' + v), anims: [...running]}); }, ms);
});

// ---------- 2.3.1 flash analysis of one CSS animation ----------
A.flashOf = a => {
  const eff = a.effect; if (!eff || !eff.target) return null;
  let kf; try { kf = eff.getKeyframes(); } catch (e) { return null; }
  const props = new Set(); kf.forEach(k => Object.keys(k).forEach(p => props.add(p)));
  const lumProps = ['opacity', 'color', 'backgroundColor', 'visibility', 'filter', 'boxShadow', 'borderColor', 'fill', 'stroke', 'outlineColor'];
  if (!lumProps.some(p => props.has(p))) return null;
  const timing = eff.getComputedTiming(), dur = timing.duration;
  if (!dur || !isFinite(dur) || dur <= 0) return null;
  const tgt = eff.target, cs = getComputedStyle(tgt, eff.pseudoElement || null);
  const d = document.createElement('div'); d.setAttribute('data-a11y-ignore', '');
  d.style.cssText = 'position:fixed;left:-9999px;top:0;width:10px;height:10px;pointer-events:none';
  d.style.color = cs.color; d.style.backgroundColor = cs.backgroundColor;
  document.body.appendChild(d);
  const clean = kf.map(k => { const o = {}; for (const [p, v] of Object.entries(k)) if (!['computedOffset', 'composite'].includes(p)) o[p] = v; return o; });
  let a2; try { a2 = d.animate(clean, {duration: dur, easing: eff.getTiming().easing, fill: 'both'}); } catch (e) { d.remove(); return null; }
  a2.pause();
  const bg = A.bgOf(tgt.parentElement || tgt);
  const hasText = !!(A.ownText(tgt) || (eff.pseudoElement && cs.content && cs.content !== 'none' && cs.content !== '""'));
  const extra = [];
  if (parseFloat(cs.borderTopWidth) > 0) extra.push(A.rgb(cs.borderTopColor));
  const sh = (cs.boxShadow || '').match(/rgba?\([^)]+\)/g); if (sh) sh.forEach(s => extra.push(A.rgb(s)));
  const series = [];
  for (let t = 0; t <= dur; t += 10) {
    a2.currentTime = Math.min(t, dur - 0.01);
    const s = getComputedStyle(d); const op = parseFloat(s.opacity) * (s.visibility === 'hidden' ? 0 : 1);
    const cands = [];
    if (hasText) cands.push(A.rgb(s.color));
    const b = A.rgb(s.backgroundColor); if (b && b.a > 0) cands.push(b);
    extra.forEach(c => c && cands.push(c));
    let L = A.lum(bg);
    for (const c of cands) if (c) L = Math.max(L, A.lum(A.blend(c, bg, op * (c.a == null ? 1 : c.a))));
    series.push(L);
  }
  a2.cancel(); d.remove();
  const reps = Math.max(1, Math.min(isFinite(timing.iterations) ? Math.ceil(timing.iterations) : 99, Math.ceil(3000 / dur) + 1));
  const full = []; for (let i = 0; i < reps; i++) full.push(...series);
  const times = [];  let ref = full[0], dir = 0;
  full.forEach((v, i) => {
    if (dir !== -1 && v <= ref - 0.1 && Math.min(ref, v) < 0.8) { times.push(i * 10); dir = -1; ref = v; }
    else if (dir !== 1 && v >= ref + 0.1 && Math.min(ref, v) < 0.8) { times.push(i * 10); dir = 1; ref = v; }
    else if ((dir === -1 && v < ref) || (dir === 1 && v > ref)) ref = v;
  });
  let peak = 0; for (let i = 0; i < times.length; i++) { let j = i; while (j < times.length && times[j] - times[i] < 1000) j++; peak = Math.max(peak, j - i); }
  const r = tgt.getBoundingClientRect();
  return {desc: A.describeAnim(a), flashesPerSecond: Math.floor(peak / 2), transitions: times.length, area: Math.round(r.width * r.height)};
};
A.flashScan = () => { const out = [];
  A.grab();
  for (const a of A.allAnims) { if (a.__a11yDone) continue; a.__a11yDone = true;
    const f = A.flashOf(a); if (f) out.push(f); }
  return out; };
A.toggleRate = () => { const out = [];
  for (const [el, ts] of A.toggles) { let peak = 0;
    for (let i = 0; i < ts.length; i++) { let j = i; while (j < ts.length && ts[j] - ts[i] < 1000) j++; peak = Math.max(peak, j - i); }
    if (peak > 6) out.push(A.name(el) + ' changes class/style ' + peak + ' times in 1 s'); }
  return out; };
})();
"""

# The clipping measure, as in _verify_no_clipping.py.
CLIP = r"""
() => {
  const W = window.innerWidth, out = [];
  const name = window.__a11y.name;
  const visible = e => { const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const scrollsX = cs => cs.overflowX === 'auto' || cs.overflowX === 'scroll';
  const clips = cs => ['hidden', 'clip'].includes(cs.overflowX) || ['hidden', 'clip'].includes(cs.overflowY);
  if (document.documentElement.scrollWidth > W) out.push(`page scrolls sideways: scrollWidth ${document.documentElement.scrollWidth} > ${W}`);
  for (const e of document.body.querySelectorAll('*')) {
    if (e.closest('svg') && e.tagName.toLowerCase() !== 'svg') continue;
    if (e.closest('[data-a11y-ignore]') || !visible(e)) continue;
    const cs = getComputedStyle(e);
    if (e.classList.contains('skip')) continue;
    if (e.closest('[aria-hidden="true"]') && getComputedStyle(e.closest('[aria-hidden="true"]')).position === 'absolute') continue;
    if (e.clientWidth > 0 && e.scrollWidth > e.clientWidth + 1 && !scrollsX(cs) && cs.display !== 'inline')
      out.push(`overflows its own box (${e.scrollWidth} > ${e.clientWidth}): ${name(e)}`);
    if (cs.textOverflow === 'ellipsis' && e.scrollWidth > e.clientWidth + 1) out.push(`ellipsis truncating: ${name(e)}`);
    const r = e.getBoundingClientRect();
    let inScroller = false; for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) if (scrollsX(getComputedStyle(a))) { inScroller = true; break; }
    if (!inScroller && cs.position !== 'fixed' && (r.right > W + 1 || r.left < -1))
      out.push(`outside the viewport (${Math.round(r.left)}..${Math.round(r.right)} of ${W}): ${name(e)}`);
    const p = e.parentElement;
    if (p && p !== document.body && cs.position !== 'fixed') {
      const pcs = getComputedStyle(p);
      if (!scrollsX(pcs) && pcs.display !== 'inline' && pcs.display !== 'contents') {
        const pr = p.getBoundingClientRect();
        const horiz = r.left < pr.left - 1 || r.right > pr.right + 1;
        const vert = r.top < pr.top - 1 || r.bottom > pr.bottom + 1;
        if (horiz || (vert && clips(pcs)))
          out.push(`sticks out of ${name(p).split(' ')[0]}${vert && clips(pcs) ? ' (clipped vertically)' : ''}: ${name(e)}`);
      }
    }
  }
  return [...new Set(out)];
}
"""

# 1.4.12: no two pieces of text overlap.
OVERLAP = r"""
() => {
  const A = window.__a11y, boxes = [], out = [];
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement; if (!el || el.closest('svg, [data-a11y-ignore], .skip')) continue;
    if (el.closest('[aria-hidden="true"]')) continue;
    if (!A.visible(el) || A.opacity(el) < 0.05) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const b of r.getClientRects()) if (b.width > 1 && b.height > 1) boxes.push({b, el, t: n.textContent.trim().slice(0, 24)});
  }
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const p = boxes[i], q = boxes[j]; if (p.el === q.el) continue;
    const ox = Math.min(p.b.right, q.b.right) - Math.max(p.b.left, q.b.left);
    const oy = Math.min(p.b.bottom, q.b.bottom) - Math.max(p.b.top, q.b.top);
    // glyph boxes of adjacent lines touch; count a real overlap only
    if (ox > 2 && oy > Math.min(p.b.height, q.b.height) * 0.35)
      out.push(`text overlaps: "${p.t}" (${A.name(p.el).split(' ')[0]}) and "${q.t}" (${A.name(q.el).split(' ')[0]})`);
  }
  return [...new Set(out)].slice(0, 30);
}
"""

BASICS = r"""
(cfg) => {
  const A = window.__a11y, out = [];
  const lang = document.documentElement.getAttribute('lang');
  if (!lang || !/^[a-z]{2,3}(-[A-Za-z0-9]+)*$/.test(lang)) out.push(`html lang is "${lang}"`);
  const title = document.title.trim();
  if (title.length < 12 || !title.includes(cfg.site)) out.push(`title "${title}" is not descriptive (>= 12 chars, names ${cfg.site})`);
  // landmarks
  const inSect = e => !!e.parentElement.closest('article, aside, main, nav, section');
  const banners = [...document.querySelectorAll('header')].filter(h => !inSect(h));
  const infos = [...document.querySelectorAll('footer')].filter(f => !inSect(f));
  if (banners.length !== 1) out.push(`${banners.length} page-level <header> (banner) landmarks, want 1`);
  if (infos.length !== 1) out.push(`${infos.length} page-level <footer> (contentinfo) landmarks, want 1`);
  const mains = document.querySelectorAll('main, [role="main"]');
  if (mains.length !== 1) out.push(`${mains.length} <main> landmarks, want 1`);
  const navs = [...document.querySelectorAll('nav, [role="navigation"]')];
  if (!navs.length) out.push('no <nav> landmark');
  const navNames = navs.map(n => (n.getAttribute('aria-label') || (n.getAttribute('aria-labelledby') ? A.accName(n) : '')).trim());
  navNames.forEach((l, i) => { if (!l) out.push(`nav without a label: ${A.name(navs[i])}`); });
  const dup = navNames.filter((l, i) => l && navNames.indexOf(l) !== i);
  if (dup.length) out.push(`two navs share the label "${dup[0]}"`);
  // headings
  const hs = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')].filter(h => getComputedStyle(h).display !== 'none' || h.closest('details'));
  const lv = h => h.getAttribute('role') === 'heading' ? parseInt(h.getAttribute('aria-level') || '2') : parseInt(h.tagName[1]);
  const h1s = hs.filter(h => lv(h) === 1);
  if (h1s.length !== 1) out.push(`${h1s.length} h1 elements, want exactly 1`);
  if (hs.length && lv(hs[0]) !== 1) out.push(`first heading is h${lv(hs[0])}: ${A.name(hs[0])}`);
  for (let i = 1; i < hs.length; i++) if (lv(hs[i]) > lv(hs[i - 1]) + 1)
    out.push(`heading level skipped: h${lv(hs[i - 1])} then h${lv(hs[i])} ${A.name(hs[i])}`);
  hs.forEach(h => { if (!A.accName(h)) out.push(`empty heading ${A.name(h)}`); });
  // links
  const generic = /^(click here|here|more|read more|learn more|link|this|go|details|#|→|&rarr;)$/i;
  const byName = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    const nm = A.accName(a), href = a.href.replace(/\/$/, '');
    if (!nm) { out.push(`link without a name: ${A.name(a)} -> ${a.getAttribute('href')}`); continue; }
    if (generic.test(nm)) out.push(`link name "${nm}" means nothing out of context -> ${a.getAttribute('href')}`);
    const key = nm.toLowerCase();
    if (!byName.has(key)) byName.set(key, new Set()); byName.get(key).add(href);
    const al = a.getAttribute('aria-label'); const vis = (a.innerText || '').trim();
    const norm = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '');
    if (al && vis && !norm(al).includes(norm(vis))) out.push(`aria-label "${al}" does not contain the visible text "${vis}" (2.5.3)`);
    const tg = (a.getAttribute('target') || '').toLowerCase();
    if (tg && !['_self', '_parent', '_top'].includes(tg) && !/new (tab|window)/i.test(nm))
      out.push(`link opens a new tab without saying so: "${nm}"`);
  }
  for (const [nm, hrefs] of byName) if (hrefs.size > 1) out.push(`link name "${nm}" points to ${hrefs.size} different places: ${[...hrefs].slice(0, 3).join(', ')}`);
  // graphics
  for (const s of document.querySelectorAll('svg')) {
    if (s.closest('[aria-hidden="true"]')) continue;
    if (s.parentElement.closest('svg')) continue;
    const named = s.getAttribute('role') === 'img' && (s.getAttribute('aria-label') || s.getAttribute('aria-labelledby') || s.querySelector(':scope > title'));
    if (!named) out.push(`svg neither aria-hidden nor a named image: ${A.name(s.parentElement)}`);
  }
  for (const i of document.querySelectorAll('img')) if (!i.hasAttribute('alt')) out.push(`img without alt: ${i.getAttribute('src')}`);
  for (const r of document.querySelectorAll('[role="img"]')) if (!A.accName(r) || A.accName(r).length < 3) out.push(`role=img without a name: ${A.name(r)}`);
  for (const [sel, words] of Object.entries(cfg.illus || {})) {
    const el = document.querySelector(sel);
    if (!el) { out.push(`illustration ${sel} not found`); continue; }
    const fig = el.closest('figure'); const cap = fig && fig.querySelector('figcaption');
    const alt = (el.getAttribute('role') === 'img' ? A.accName(el) : '') + ' ' + (cap ? cap.textContent : '');
    const miss = words.filter(w => !alt.toLowerCase().includes(w.toLowerCase()));
    if (el.getAttribute('role') !== 'img') out.push(`illustration ${sel} is not marked role="img" with a text alternative`);
    if (miss.length) out.push(`illustration ${sel} text alternative lacks: ${miss.join(', ')}`);
  }
  // accessibility statement in the footer
  const foot = infos[0] || document.querySelector('footer');
  const st = foot && [...foot.querySelectorAll('a[href]')].find(a => /\/accessibility(\.html)?$/.test(new URL(a.href).pathname) && /accessibility/i.test(A.accName(a)));
  if (!st) out.push('footer has no "Accessibility" link to the accessibility statement');
  return out;
}
"""

CONTRAST = r"""
() => {
  const A = window.__a11y, out = [];
  for (const e of document.body.querySelectorAll('*')) {
    if (e.closest('svg, [aria-hidden="true"], [data-a11y-ignore]') || !A.visible(e) || !A.ownText(e)) continue;
    if (e.classList.contains('skip') && document.activeElement !== e) continue;
    const r = e.getBoundingClientRect(); if (r.right < 0 || r.bottom < -5000) continue;
    const cs = getComputedStyle(e), fg = A.rgb(cs.color); if (!fg) continue;
    const bg = A.bgOf(e), k = A.opacity(e) * (fg.a == null ? 1 : fg.a);
    const ratio = A.ratio(A.blend(fg, bg, k), bg);
    const fs = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (fs >= 24 || (bold && fs >= 18.66)) ? 3 : 4.5;
    if (ratio < need - 0.01) out.push(`1.4.3 contrast ${ratio.toFixed(2)} < ${need}: ${A.name(e)}`);
  }
  // 1.4.11: interactive elements are identified by passing text, or by an icon / border of >= 3:1
  const sel = 'a[href],button,summary,input,select,textarea,[tabindex]:not([tabindex="-1"])';
  for (const e of document.querySelectorAll(sel)) {
    if (!A.visible(e) || e.closest('[aria-hidden="true"]') || e.classList.contains('skip')) continue;
    if ((e.innerText || '').trim()) continue;
    const bg = A.bgOf(e); let best = 0;
    const cs = getComputedStyle(e);
    if (parseFloat(cs.borderTopWidth) >= 1) { const b = A.rgb(cs.borderTopColor); if (b) best = Math.max(best, A.ratio(A.blend(b, bg, b.a), bg)); }
    for (const g of e.querySelectorAll('svg, svg *')) { const gs = getComputedStyle(g);
      for (const c of [gs.fill, gs.stroke]) { const x = A.rgb(c); if (x && x.a > 0) best = Math.max(best, A.ratio(A.blend(x, bg, x.a * A.opacity(g)), bg)); } }
    if (best < 3) out.push(`1.4.11 control with no text and no 3:1 icon/border (best ${best.toFixed(2)}): ${A.name(e)}`);
  }
  return out;
}
"""

TABBABLES = r"""
() => {
  const A = window.__a11y;
  const sel = 'a[href],area[href],button,input:not([type=hidden]),select,textarea,summary,iframe,[tabindex],[contenteditable="true"],[contenteditable=""],audio[controls],video[controls]';
  const out = [], bad = [];
  for (const e of document.querySelectorAll(sel)) {
    if (e.tabIndex > 0) bad.push(`positive tabindex ${e.tabIndex}: ${A.name(e)}`);
    if (e.disabled || e.tabIndex < 0 || e.closest('[inert]') || !A.visible(e)) continue;
    if (e.tagName === 'SUMMARY' && e.parentElement.tagName === 'DETAILS' && e.parentElement.querySelector('summary') !== e) continue;
    out.push({k: A.tag(e), name: A.name(e)});
    // visual order: nothing on the way to the root reorders it
    for (let n = e; n && n.parentElement; n = n.parentElement) {
      const cs = getComputedStyle(n), ps = getComputedStyle(n.parentElement);
      if (/flex|grid/.test(ps.display) && cs.order !== '0') bad.push(`CSS order ${cs.order} moves ${A.name(n)} away from DOM order`);
      if (/flex/.test(ps.display) && /reverse/.test(ps.flexDirection)) bad.push(`flex-direction ${ps.flexDirection} reverses ${A.name(n.parentElement)}`);
    }
  }
  return {list: out, bad: [...new Set(bad)]};
}
"""

ACTIVE = r"""
() => {
  const A = window.__a11y, e = document.activeElement;
  if (!e || e === document.body || e === document.documentElement) return {body: true};
  A.last = e;
  const r = e.getBoundingClientRect();
  const W = innerWidth, H = innerHeight;
  const vx0 = Math.max(0, r.left), vx1 = Math.min(W, r.right), vy0 = Math.max(0, r.top), vy1 = Math.min(H, r.bottom);
  let obscured = null;
  const frags = [...e.getClientRects()].filter(f => f.width > 0 && f.height > 0);
  const f0 = frags.find(f => f.right > 0 && f.left < W && f.bottom > 0 && f.top < H);
  if (vx1 > vx0 && vy1 > vy0) {
    const px = f0 ? (Math.max(0, f0.left) + Math.min(W, f0.right)) / 2 : (vx0 + vx1) / 2;
    const py = f0 ? (Math.max(0, f0.top) + Math.min(H, f0.bottom)) / 2 : (vy0 + vy1) / 2;
    const hit = document.elementFromPoint(px, py);
    if (hit && hit !== e && !e.contains(hit) && !(hit.contains(e) && getComputedStyle(e).pointerEvents === 'none')) obscured = A.name(hit);
  }
  return {body: false, k: A.tag(e), dom: A.domIndex(e), name: A.name(e), tag: e.tagName.toLowerCase(),
          rect: [r.left, r.top, r.right, r.bottom], frags: frags.map(f => [f.left, f.top, f.right, f.bottom]), opacity: A.opacity(e), visible: A.visible(e),
          focusVisible: e.matches(':focus-visible'), obscured,
          inMain: !!e.closest('main'), href: e.getAttribute('href'), accName: A.accName(e)};
}
"""


def lum_arr(img):
    a = np.asarray(img.convert("RGB"), dtype=np.float64) / 255.0
    a = np.where(a <= 0.03928, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


class Run:
    """One page in one browser context: the checks share a loaded, settled page."""

    def __init__(self, page, label, W, H, report):
        self.page, self.label, self.W, self.H, self.report = page, label, W, H, report

    def ev(self, js, arg=None):
        return self.page.evaluate(js, arg) if arg is not None else self.page.evaluate(js)

    # ---------- focus indicator, measured in pixels ----------
    def measure_focus(self, info):
        pg = self.page
        for _ in range(20):                       # reveals may still be fading in
            if info.get("opacity", 1) >= 0.999:
                break
            pg.wait_for_timeout(100)
            info = self.ev(ACTIVE)
        probs = []
        if info.get("body"):
            return ["focus lost to <body>"]
        who = info["name"]
        if not info["visible"] or info["opacity"] < 0.999:
            probs.append(f"focused but not visible (opacity {info['opacity']:.2f}): {who}")
        if info["obscured"]:
            probs.append(f"focused element covered by {info['obscured']}: {who}")
        if not info["focusVisible"]:
            probs.append(f"does not match :focus-visible on keyboard focus: {who}")
        x0, y0, x1, y1 = info["rect"]
        if x1 <= 0 or y1 <= 0 or x0 >= self.W or y0 >= self.H:
            return probs + [f"focused element is off screen ({[round(v) for v in info['rect']]}): {who}"]
        cx0, cy0 = max(0, int(x0) - 8), max(0, int(y0) - 8)
        cx1, cy1 = min(self.W, int(x1) + 9), min(self.H, int(y1) + 9)
        clip = {"x": cx0, "y": cy0, "width": cx1 - cx0, "height": cy1 - cy0}
        on = Image.open(io.BytesIO(pg.screenshot(clip=clip)))
        self.ev("() => window.__a11y.last.blur()")
        pg.wait_for_timeout(30)
        off = Image.open(io.BytesIO(pg.screenshot(clip=clip)))
        self.ev("() => window.__a11y.last.focus({preventScroll: true})")
        la, lb = lum_arr(on), lum_arr(off)
        ratio = (np.maximum(la, lb) + 0.05) / (np.minimum(la, lb) + 0.05)
        changed = int((ratio >= 3.0).sum())
        # minimum area: a 2 px ring along each side of the element that is on screen
        w, h = x1 - x0, y1 - y0
        # (a side cut off by the window edge cannot show a ring and is not counted;
        # an inline element that wraps is outlined line fragment by line fragment)
        need = 0.0
        for fx0, fy0, fx1, fy1 in (info.get("frags") or [info["rect"]]) if len(info.get("frags") or []) > 1 else [info["rect"]]:
            fw, fh = fx1 - fx0, fy1 - fy0
            if fy0 >= 6: need += 2 * fw
            if fy1 <= self.H - 6: need += 2 * fw
            if fx0 >= 6: need += 2 * fh
            if fx1 <= self.W - 6: need += 2 * fh
        need *= 0.9
        if changed < need and os.environ.get("A11Y_DEBUG"):
            stem = Path(os.environ["A11Y_DEBUG"]) / re.sub(r"\W+", "_", f"{self.label}_{who}")[:90]
            on.save(f"{stem}_on.png"); off.save(f"{stem}_off.png")
        if changed < need:
            probs.append(f"focus indicator too weak: {changed}px change at >=3:1, need {int(need)} (2px ring): {who}")
        return probs

    # ---------- Tab through the whole page ----------
    def keyboard(self, menu_expected):
        pg, probs = self.page, []
        tb = self.ev(TABBABLES)
        probs += tb["bad"]
        expected = {t["k"]: t["name"] for t in tb["list"]}
        seen, order, first = [], [], None
        limit = len(expected) * 2 + 25
        trapped = True
        for _ in range(limit):
            pg.keyboard.press("Tab")
            pg.wait_for_timeout(40)
            info = self.ev(ACTIVE)
            if info["body"]:
                trapped = False
                break
            if info["k"] in seen:
                probs.append(f"focus came back to {info['name']} before leaving the page (loop/trap)")
                break
            seen.append(info["k"])
            order.append(info["dom"])
            if first is None:
                first = info
            probs += self.measure_focus(info)
        else:
            pass
        if trapped:
            probs.append(f"focus never left the page after {len(seen)} Tab presses (keyboard trap)")
        missing = [n for k, n in expected.items() if k not in seen]
        for m in missing:
            probs.append(f"never reached with Tab: {m}")
        if order != sorted(order):
            probs.append("Tab order differs from DOM order")
        # skip link: the first stop, on screen, and it moves focus into main
        if not first or not re.search(r"skip", first.get("accName", ""), re.I) or not (first.get("href") or "").startswith("#"):
            probs.append(f"first Tab stop is not a skip link: {first and first.get('name')}")
        else:
            x0, y0, x1, y1 = first["rect"]
            if x0 < 0 or y0 < 0 or x1 > self.W or y1 > self.H:
                probs.append("skip link is not fully on screen when focused")
            # after the last element Tab wraps to the top again: the skip link
            pg.keyboard.press("Tab")
            pg.wait_for_timeout(60)
            again = self.ev(ACTIVE)
            if again.get("k") != first["k"]:
                pg.keyboard.press("Tab"); pg.wait_for_timeout(60); again = self.ev(ACTIVE)
            if again.get("k") == first["k"]:
                pg.keyboard.press("Enter")
                pg.wait_for_timeout(500)
                pg.keyboard.press("Tab")
                pg.wait_for_timeout(80)
                after = self.ev(ACTIVE)
                if after.get("body") or not after.get("inMain"):
                    probs.append(f"skip link does not move focus into <main> (next stop: {after.get('name')})")
            else:
                probs.append("could not get back to the skip link after the last element")
        probs += self.menu(menu_expected)
        probs += self.details()
        return probs

    def menu(self, menu_expected):
        pg, probs = self.page, []
        btn = self.ev(r"""() => { const b = [...document.querySelectorAll('button[aria-expanded][aria-controls]')]
            .find(b => window.__a11y.visible(b)); if (!b) return null; window.__a11y.menuBtn = b;
            return {name: window.__a11y.name(b), ctl: b.getAttribute('aria-controls')}; }""")
        if not btn:
            if menu_expected:
                probs.append("no visible menu button (button[aria-expanded][aria-controls]) at this width")
            return probs
        state = r"""() => { const b = window.__a11y.menuBtn, c = document.getElementById(b.getAttribute('aria-controls'));
            const a = document.activeElement;
            return {expanded: b.getAttribute('aria-expanded'), shown: !!c && window.__a11y.visible(c),
                    activeIsBtn: a === b, activeIn: !!c && c.contains(a), active: window.__a11y.name(a)}; }"""
        focus_btn = "() => window.__a11y.menuBtn.focus()"
        self.ev(focus_btn)
        pg.keyboard.press("Enter"); pg.wait_for_timeout(200)
        s = self.ev(state)
        if s["expanded"] != "true" or not s["shown"]:
            return probs + [f"Enter on {btn['name']} does not open the menu ({s})"]
        pg.keyboard.press("Tab"); pg.wait_for_timeout(60)
        s = self.ev(state)
        if not s["activeIn"]:
            probs.append(f"Tab after opening the menu does not go into it (went to {s['active']})")
        n = 0
        while s["activeIn"] and n < 60:
            probs += self.measure_focus(self.ev(ACTIVE))
            pg.keyboard.press("Tab"); pg.wait_for_timeout(60)
            s = self.ev(state); n += 1
        info = self.ev(ACTIVE)
        if not info.get("body") and s["shown"] and info.get("obscured"):
            probs.append(f"Tab out of the open menu leaves focus hidden under it ({info['name']} covered by {info['obscured']})")
        # Escape closes and returns focus
        self.ev(focus_btn)
        if self.ev(state)["expanded"] != "true":
            pg.keyboard.press("Enter"); pg.wait_for_timeout(150)
        pg.keyboard.press("Tab"); pg.wait_for_timeout(60)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(150)
        s = self.ev(state)
        if s["expanded"] != "false" or s["shown"]:
            probs.append("Escape does not close the menu")
        if not s["activeIsBtn"]:
            probs.append(f"Escape does not return focus to the menu button (focus on {s['active']})")
        # Enter toggles closed, Space opens
        self.ev(focus_btn)
        pg.keyboard.press("Enter"); pg.wait_for_timeout(120)
        pg.keyboard.press("Enter"); pg.wait_for_timeout(120)
        if self.ev(state)["expanded"] != "false":
            probs.append("Enter on the open menu button does not close it")
        pg.keyboard.press("Space"); pg.wait_for_timeout(120)
        if self.ev(state)["expanded"] != "true":
            probs.append("Space does not open the menu")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(120)
        return probs

    def details(self):
        pg, probs = self.page, []
        n = self.ev("() => [...document.querySelectorAll('details')].filter(d => window.__a11y.visible(d)).length")
        for i in range(min(n, 4)):
            st = f"""() => {{ const d = [...document.querySelectorAll('details')].filter(d => window.__a11y.visible(d))[{i}];
                const body = [...d.children].find(c => c.tagName !== 'SUMMARY');
                return {{open: d.open, bodyShown: !!body && window.__a11y.visible(body), name: window.__a11y.name(d.querySelector('summary'))}}; }}"""
            self.ev(f"""() => [...document.querySelectorAll('details')].filter(d => window.__a11y.visible(d))[{i}].querySelector('summary').focus()""")
            s0 = self.ev(st)
            pg.keyboard.press("Enter"); pg.wait_for_timeout(120)
            s1 = self.ev(st)
            if s1["open"] == s0["open"] or (s1["open"] and not s1["bodyShown"]):
                probs.append(f"Enter does not toggle <details> {s0['name']}")
            pg.keyboard.press("Space"); pg.wait_for_timeout(120)
            s2 = self.ev(st)
            if s2["open"] != s0["open"]:
                probs.append(f"Space does not toggle <details> {s0['name']}")
            if s2["open"] != s0["open"]:
                self.ev(f"""() => {{ [...document.querySelectorAll('details')].filter(d => window.__a11y.visible(d))[{i}].open = {str(s0['open']).lower()}; }}""")
        return probs


# ───────────────────── motion: scan, flashes, pause ──────────────────────
def settle_scan(run, motion_on):
    """Scroll screen by screen. Returns (long-motion stops, flash problems, infinite animations)."""
    pg = run.page
    long_stops, flashes, flash_log = [], [], []
    height = run.ev("document.documentElement.scrollHeight")
    y = 0
    while True:
        run.ev(f"window.scrollTo({{top: {y}, behavior: 'instant'}})")
        pg.wait_for_timeout(300)
        t0 = time.time()
        r = run.ev("window.__a11y.observe(1000)")
        for f in run.ev("window.__a11y.flashScan()"):
            flash_log.append(f)
        quiet = not r["muts"] and not r["anims"]
        if motion_on and not quiet:
            while time.time() - t0 < 5.0:
                r = run.ev("window.__a11y.observe(700)")
                flash_log.extend(run.ev("window.__a11y.flashScan()"))
            r = run.ev("window.__a11y.observe(1500)")
            flash_log.extend(run.ev("window.__a11y.flashScan()"))
            if r["muts"] or r["anims"]:
                long_stops.append({"y": y, "what": (r["anims"] + r["muts"])[:6]})
        elif not motion_on and not quiet:
            r2 = run.ev("window.__a11y.observe(1500)")
            if r2["muts"] or r2["anims"]:
                long_stops.append({"y": y, "what": (r2["anims"] + r2["muts"])[:6]})
        if y + run.H >= height:
            break
        y += run.H
        height = run.ev("document.documentElement.scrollHeight")
    for f in flash_log:
        if f["flashesPerSecond"] > 3:
            flashes.append(f"2.3.1 {f['desc']} flashes {f['flashesPerSecond']}x per second (area {f['area']} px2)")
    flashes += [f"2.3.1 {x}" for x in run.ev("window.__a11y.toggleRate()")]
    infinite = sorted({v["desc"] for v in run.ev("[...window.__a11y.seenAnims.values()]") if v["iterations"] is None or v["iterations"] == float("inf")})
    run.ev("window.scrollTo({top: 0, behavior: 'instant'})")
    pg.wait_for_timeout(300)
    return long_stops, flashes, flash_log, infinite


FIND_PAUSE = r"""() => { const b = [...document.querySelectorAll('button[aria-pressed]')]
  .find(b => /(pause|stop)/i.test(window.__a11y.accName(b)) && /(anim|motion)/i.test(window.__a11y.accName(b)));
  if (!b) return null; window.__a11y.pause = b;
  return {k: window.__a11y.tag(b), name: window.__a11y.accName(b), pressed: b.getAttribute('aria-pressed'), visible: window.__a11y.visible(b)}; }"""

HIDDEN_TEXT = r"""() => { const A = window.__a11y, out = [];
  for (const e of document.querySelectorAll('main *, header *, footer *')) {
    if (e.closest('svg, details:not([open]) > :not(summary)') || !A.ownText(e)) continue;
    const cs = getComputedStyle(e); if (cs.display === 'none') continue;
    let op = 1, moved = null;
    for (let n = e; n && n !== document.documentElement; n = n.parentElement) {
      const s = getComputedStyle(n); op *= parseFloat(s.opacity); if (s.visibility === 'hidden') op = 0;
      if (s.display === 'none') { op = -1; break; }
      if (s.clipPath && /inset\([^)]*100%/.test(s.clipPath)) moved = A.name(n); }
    if (op === -1) continue;
    if (op < 0.999) out.push(`text hidden (opacity ${op.toFixed(2)}): ${A.name(e)}`);
    if (moved) out.push(`text clipped away by ${moved}`);
  } return out.slice(0, 12); }"""


def pause_check(run, long_stops, seen_keys, base_url):
    pg, probs = run.page, []
    info = run.ev(FIND_PAUSE)
    what = "; ".join(f"at y={s['y']}: {', '.join(s['what'][:3])}" for s in long_stops[:4])
    if not info:
        return [f"2.2.2 motion still running 5 s after arriving, and no 'Pause animations' button[aria-pressed]: {what}"]
    if not info["visible"]:
        probs.append("2.2.2 the pause control is not visible")
    if seen_keys is not None and info["k"] not in seen_keys:
        probs.append("2.2.2 the pause control is not reachable with Tab")
    # operate it with the keyboard
    run.ev("() => window.__a11y.pause.focus()")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(200)
    if run.ev("() => window.__a11y.pause.getAttribute('aria-pressed')") != "true":
        return probs + ["2.2.2 Enter on the pause control does not set aria-pressed=true"]
    for s in long_stops:
        run.ev(f"window.scrollTo({{top: {s['y']}, behavior: 'instant'}})")
        pg.wait_for_timeout(900)
        r = run.ev("window.__a11y.observe(2000)")
        if r["muts"] or r["anims"]:
            probs.append(f"2.2.2 paused, but still moving at y={s['y']}: {', '.join((r['anims'] + r['muts'])[:4])}")
        probs += [f"2.2.2 paused: {x}" for x in run.ev(HIDDEN_TEXT)]
    # survives a reload
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(1200)
    info2 = run.ev(FIND_PAUSE)
    if not info2 or info2["pressed"] != "true":
        probs.append("2.2.2 the paused state does not survive a reload")
    else:
        r = run.ev("window.__a11y.observe(1500)")
        if r["anims"] or r["muts"]:
            probs.append(f"2.2.2 after reload while paused, still moving: {', '.join((r['anims'] + r['muts'])[:4])}")
        probs += [f"2.2.2 reloaded while paused: {x}" for x in run.ev(HIDDEN_TEXT)]
        run.ev("() => window.__a11y.pause.focus()")
        pg.keyboard.press("Space")
        pg.wait_for_timeout(300)
        if run.ev("() => window.__a11y.pause.getAttribute('aria-pressed')") != "false":
            probs.append("2.2.2 Space on the pause control does not resume (aria-pressed stays true)")
    run.ev("() => { try { localStorage.clear(); } catch (e) {} }")
    return probs


# ─────────────────────────────── main ───────────────────────────────────
def main(only):
    from playwright.sync_api import sync_playwright

    results: dict[str, list[str]] = {}
    reviews: dict[str, set] = {}

    def report(key, problems):
        results[key] = list(problems)
        print(("FAIL " if problems else "ok   ") + key + (f": {len(problems)}" if problems else ""), flush=True)
        for p in problems[:25]:
            print("   -", p)
        if len(problems) > 25:
            print(f"   ... and {len(problems) - 25} more")

    pages = [p for p in PAGES if not only or p in only]
    report("pages exist", [f"{p} missing" for p in pages if not (ROOT / p).exists()])
    pages = [p for p in pages if (ROOT / p).exists()]

    axe = axe_source()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(PagesHandler, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"

    # statement content (static)
    st = ROOT / STATEMENT
    if not only or STATEMENT in only:
        sp = []
        if not st.exists():
            sp.append(f"{STATEMENT} does not exist")
        else:
            src = st.read_text(encoding="utf-8")
            txt = re.sub(r"<[^>]+>", " ", re.sub(r"<!--.*?-->", " ", src, flags=re.S))
            txt = re.sub(r"\s+", " ", txt)
            need = {
                "a compliance status (fully / partially / not compliant)": r"\b(fully|partially|not) compliant\b",
                "WCAG 2.1 Level AA": r"WCAG 2\.1[^.]{0,40}\bAA\b",
                "EN 301 549 V3.2.1": r"EN 301 549 V3\.2\.1",
                "the statement date": r"27 September 2026|2026-09-27",
                "the method: axe-core": r"axe-core",
                "the method: keyboard": r"keyboard",
                "the method: zoom": r"zoom",
                "the method: screen reader": r"screen reader",
                "non-compliant section": r"[Nn]on-compliant",
                "exempt section": r"[Ee]xempt",
                "disproportionate burden section": r"[Dd]isproportionate burden",
                "one-month response": r"one month|a month",
                "private and voluntary": r"(?=.*\bprivate\b)(?=.*\bvoluntar)",
            }
            for what, rx in need.items():
                if not re.search(rx, txt, re.I | re.S):
                    sp.append(f"statement does not state {what}")
            if ISSUES_URL not in src:
                sp.append(f"statement does not link {ISSUES_URL}")
            # DELIBERATE CHANGE 2026-10-03: this used to demand an owner TODO and
            # forbid any email, while no contact address existed. The project now
            # has one (contact@airacegp.com, on its own domain, no personal data),
            # so the statement must offer it, and only it.
            mails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", txt))
            if "mailto:contact@airacegp.com" not in src:
                sp.append("statement does not offer contact@airacegp.com")
            if mails - {"contact@airacegp.com"}:
                sp.append(f"statement contains another email address: {sorted(mails)}")
            if re.search(r"ombuds|m[ée]diateur|\bSIP\b|Service information et presse", txt, re.I):
                sp.append("statement mentions the public-sector referral (SIP / ombudsman)")
        report(f"{STATEMENT}: required content (STMT)", sp)

    titles: dict[str, str] = {}
    with sync_playwright() as p:
        kw = {"args": ["--ignore-certificate-errors"]}
        if Path(CHROME).exists():
            kw["executable_path"] = CHROME
        browser = p.chromium.launch(**kw)

        def new(w, h, motion, init=None):
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,
                                      reduced_motion=motion, ignore_https_errors=True)
            ctx.add_init_script(HELPERS)
            if init:
                ctx.add_init_script(init)
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
            pg.on("console", lambda m: errs.append(f"console.error: {m.text[:160]}") if m.type == "error" else None)
            return ctx, pg, errs

        def goto(pg, name):
            resp = pg.goto(base + name, wait_until="networkidle")
            pg.evaluate("document.fonts.ready.then(() => true)")
            return resp

        for name in pages:
            if name in REDIRECT_STUBS:
                ctx, pg, _ = new(1440, 900, "reduce")
                src = (ROOT / name).read_text(encoding="utf-8")
                pr = []
                if not re.search(r'<html[^>]+lang="[a-z]{2}', src): pr.append("no lang")
                if not re.search(r"<title>[^<]{12,}</title>", src): pr.append("no descriptive title")
                goto(pg, name); pg.wait_for_timeout(800)
                if pg.url.rstrip("/").endswith(name):
                    pr.append("does not redirect")
                report(f"{name}: redirect stub (lang, title, redirects)", pr)
                ctx.close()
                continue

            for motion in MOTIONS:
                for w in WIDTHS:
                    tag = f"{name} @ {w}px, motion {'on' if motion == 'no-preference' else 'reduced'}"
                    ctx, pg, errs = new(w, 900, motion)
                    goto(pg, name)
                    run = Run(pg, tag, w, 900, report)
                    pg.wait_for_timeout(600)
                    titles[name] = pg.title()

                    long_stops, flashes, flash_log, infinite = settle_scan(run, motion == "no-preference")
                    if motion == "reduce" and long_stops:
                        report(f"{tag}: nothing moves with reduced motion", [f"moving at y={s['y']}: {', '.join(s['what'][:3])}" for s in long_stops])
                    report(f"{tag}: 2.3.1 no flashing", flashes)
                    if w == 1440 and motion == "no-preference":
                        peak = max([f["flashesPerSecond"] for f in flash_log] or [0])
                        print(f"     measured: {len(flash_log)} luminance animation(s), peak {peak} flash(es)/s")
                        if flash_log:
                            worst = max(flash_log, key=lambda f: (f["flashesPerSecond"], f["area"]))
                            print(f"     worst: {worst['desc']} -> {worst['flashesPerSecond']}/s, {worst['transitions']} transitions, area {worst['area']} px2")

                    # axe
                    pg.add_script_tag(content=axe)
                    res = pg.evaluate("""() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa']},
                                         resultTypes: ['violations','incomplete']})""")
                    viol = []
                    for v in res["violations"]:
                        for n in v["nodes"][:6]:
                            viol.append(f"{v['id']} ({v['impact']}): {' '.join(n['target'])[:90]} :: {n.get('failureSummary','').splitlines()[-1][:120] if n.get('failureSummary') else ''}")
                    report(f"{tag}: axe-core wcag2a/aa + wcag21a/aa violations", viol)
                    for v in res["incomplete"]:
                        for n in v["nodes"]:
                            why = ((n.get("any") or n.get("all") or [{}])[0].get("message") or "")[:110]
                            reviews.setdefault(name, set()).add(f"{v['id']}: {' '.join(n['target'])[:70]} -- {why}")

                    report(f"{tag}: page basics (BASE)", run.ev(BASICS, {"site": SITE_NAME, "illus": ILLUSTRATIONS.get(name, {})}))
                    report(f"{tag}: 1.4.3 / 1.4.11 contrast", run.ev(CONTRAST))

                    # keyboard (animations frozen only while measuring pixels)
                    pg.add_style_tag(content=FREEZE_CSS)
                    kb = run.keyboard(menu_expected=(w < 961 and name in MENU_PAGES))
                    report(f"{tag}: keyboard (KBD)", kb)
                    seen = run.ev("() => [...document.querySelectorAll('[data-a11y-k]')].map(e => e.dataset.a11yK)")

                    if motion == "no-preference":
                        ctx.close()
                        ctx, pg, errs = new(w, 900, motion)
                        goto(pg, name); pg.wait_for_timeout(600)
                        run = Run(pg, tag, w, 900, report)
                        if long_stops:
                            run.ev(TABBABLES)  # tags every tabbable, including the pause control
                            # keyboard reachability of the control was covered by KBD (it tabs everything)
                            report(f"{tag}: 2.2.2 pause, stop, hide", pause_check(run, long_stops, None, base))
                        else:
                            report(f"{tag}: 2.2.2 pause, stop, hide (no motion lasts > 5 s)", [])
                        if w == 1440:
                            fin = [f"CSS animation repeats forever: {d}" for d in infinite]
                            if long_stops:
                                ctx.close()
                                ctx, pg, errs = new(w, 900, motion)
                                goto(pg, name)
                                run = Run(pg, tag, w, 900, report)
                                for s in long_stops:
                                    run.ev(f"window.scrollTo({{top: {s['y']}, behavior: 'instant'}})")
                                    pg.wait_for_timeout(20000)
                                    r = run.ev("window.__a11y.observe(2000)")
                                    if r["muts"] or r["anims"]:
                                        fin.append(f"still moving 20 s after arriving at y={s['y']}: {', '.join((r['anims'] + r['muts'])[:4])}")
                            report(f"{tag}: 2.2.2 every loop ends by itself", fin)
                        report(f"{tag}: no page errors", errs)
                    ctx.close()

                    # 1.4.12 text spacing at this width
                    ctx, pg, errs = new(w, 900, motion)
                    goto(pg, name)
                    pg.add_style_tag(content=TEXT_SPACING_CSS)
                    pg.wait_for_timeout(300)
                    run = Run(pg, tag, w, 900, report)
                    settle_quick(run)
                    report(f"{tag}: 1.4.12 text spacing: nothing clipped or overlapping", run.ev(CLIP) + run.ev(OVERLAP))
                    ctx.close()

                # 1.4.10 reflow and 1.4.4 zoom
                for (vw, vh, what) in ((320, 640, "1.4.10 reflow at 320 px"), (720, 450, "1.4.4 200% zoom (1440x900 at 720x450)")):
                    ctx, pg, errs = new(vw, vh, motion)
                    goto(pg, name)
                    run = Run(pg, name, vw, vh, report)
                    settle_quick(run)
                    pr = run.ev(CLIP)
                    hh = run.ev("() => { const h = document.querySelector('header'); return h && getComputedStyle(h).position === 'sticky' || h && getComputedStyle(h).position === 'fixed' ? h.getBoundingClientRect().height : 0; }")
                    if hh > vh / 3:
                        pr.append(f"sticky header is {hh}px of a {vh}px window")
                    report(f"{name}, motion {'on' if motion == 'no-preference' else 'reduced'}: {what}", pr)
                    ctx.close()
        browser.close()
    srv.shutdown()

    dups = {}
    for n, t in titles.items():
        dups.setdefault(t, []).append(n)
    report("titles unique across pages", [f'"{t}" on {", ".join(ns)}' for t, ns in dups.items() if len(ns) > 1])

    if reviews:
        print("\nREVIEW (axe could not decide; checked by a human, not failures):")
        for n, items in reviews.items():
            for it in sorted(items)[:30]:
                print(f"   {n}: {it}")
    bad = sum(len(v) for v in results.values())
    print(f"\n{bad} problem(s) in {sum(1 for v in results.values() if v)} of {len(results)} checks")
    return 1 if bad else 0


def settle_quick(run):
    """Scroll through once so scroll reveals have fired, then back to the top."""
    pg = run.page
    run.ev("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo({top: y, behavior: 'instant'});
               await new Promise(r => setTimeout(r, 90)); } window.scrollTo({top: 0, behavior: 'instant'}); }""")
    pg.wait_for_timeout(1600)


if __name__ == "__main__":
    try:
        sys.exit(main(set(sys.argv[1:])))
    except SystemExit:
        raise
    except Exception as exc:  # a crash is a failure, never a pass
        import traceback
        traceback.print_exc()
        print(f"CRASH: {exc!r}")
        sys.exit(1)
