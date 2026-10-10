#!/usr/bin/env python3
"""Stamp the library's numbers into the site's HTML.

It runs whenever icons.json is replaced with a new library build: library-release.py calls it, and it
can be run by hand from the site folder:

    python3 .github/scripts/stamp-counts.py            # rewrite the pages
    python3 .github/scripts/stamp-counts.py --check    # change nothing; exit 1 if any page is out of date

Nothing is written unless every page passes: one error and all six pages stay as they were.

Why a script and not page JavaScript: titles, descriptions, og:/twitter: tags, JSON-LD and the press
boilerplate are read by crawlers, link previews and people copying text. None of them run the page's
scripts, so the numbers have to be in the HTML itself.

The numbers are COUNTED from icons.json, the same way the About page counts them at load:
  icons      distinct first names
  shapes     every drawn variant (7 weights x stroke/fill that exist) of every distinct icon
  keywords   keyword SLOTS: the sum of every icon's searchTerms length (not distinct words)
  categories distinct categories, Popular left out (it is a flag, not a category)

Each number is found by the WORDS AFTER IT ("… icons in 7 weights", "… shapes in all"), never by its
old value, so it does not matter what the page said before.

It fails loudly instead of missing quietly:
  - a phrase that should be on a page and is not there  -> error (a copy edit moved the anchor)
  - a "<number> icons/shapes/keywords/categories" left on a page that is neither stamped, nor in the
    timeline, nor in ALLOW                               -> error (a new phrasing needs a pattern)

Never stamped: About's timeline (<ol class="tl">). Those rows are history: each keeps the count its
version had.
"""
import json
import os
import pathlib
import re
import sys

SITE = pathlib.Path(os.environ.get('SITE_DIR') or pathlib.Path(__file__).resolve().parents[2])   # the site folder: two up from .github/scripts
PAGES = ['index.html', 'about.html', 'dev.html', 'press.html', 'privacy.html', '404.html']
WEIGHTS = ['thin', 'ultralight', 'light', 'regular', 'medium', 'semibold', 'bold']

# "<number> <unit>" phrases that are NOT the library's totals and stay as they are
ALLOW = ['4 icons per row']   # a CSS comment on the homepage

NUM = r'\d[\d,]*'
# (unit, pattern with ONE group = the number, pages that must contain it)
PHRASES = [
    ('icons',      rf'({NUM})(?= open-source icons\b)',  [p for p in PAGES if p != 'press.html']),
    ('icons',      rf'({NUM})(?= icons in 7 weights\b)', PAGES),
    ('shapes',     rf'({NUM})(?= shapes in all\b)',      ['press.html']),
    ('keywords',   rf'({NUM})(?= keywords\b)',           ['press.html']),
    ('categories', rf'({NUM})(?= categories\b)',         ['press.html']),
]
# About's counters: the number shown before the script runs, and the target the count-up runs to.
# data-target stays NUMERIC (a comma there makes the counter NaN); the comma belongs to the text only.
COUNTERS = [('icons', 'iconCount', 'Icons'), ('shapes', 'shapeCount', 'Shapes')]
# regions that are never stamped and never checked
SKIP = [re.compile(r'<ol class="tl".*?</ol>', re.S)]
GENERIC = re.compile(rf'({NUM}) (?:open-source )?(icons?|shapes|keywords|categories)\b')


def count(data):
    icons = data.get('icons') or []
    seen, shapes = set(), 0
    for ic in icons:
        first = ic['name'].split('-')[0]
        if first in seen:
            continue
        seen.add(first)
        for w in WEIGHTS:
            for style in ('stroke', 'fill'):
                if (ic.get('variants', {}).get(w) or {}).get(style):
                    shapes += 1
    return {
        'icons': len(seen),
        'shapes': shapes,
        'keywords': sum(len(ic.get('searchTerms') or []) for ic in icons),
        'categories': len({ic.get('category') for ic in icons} - {'Popular', None}),
    }


def fmt(n):
    return f'{n:,}'


def split(text):
    """[(chunk, stampable)] with the skip regions cut out, in order."""
    spans = sorted((m.start(), m.end()) for rx in SKIP for m in rx.finditer(text))
    out, at = [], 0
    for a, b in spans:
        out.append((text[at:a], True)); out.append((text[a:b], False)); at = b
    out.append((text[at:], True))
    return out


def stamp(name, text, n, errors):
    changes, hits = 0, {i: 0 for i in range(len(PHRASES))}
    found = set()
    parts = []
    for chunk, live in split(text):
        if live:
            for i, (unit, pat, _) in enumerate(PHRASES):
                def put(m, unit=unit, i=i):
                    nonlocal changes
                    hits[i] += 1
                    new = fmt(n[unit])
                    changes += m.group(1) != new
                    return new
                chunk = re.sub(pat, put, chunk)
            if name == 'about.html':
                for unit, cid, word in COUNTERS:
                    rx = re.compile(rf'(id="{cid}" data-target=")(\d+)(" data-from=")(\d+)(">)({NUM})(</span> {word}\b)')
                    m = rx.search(chunk)
                    if not m:
                        continue
                    found.add(cid)
                    lead = int(m.group(2)) - int(m.group(4))            # the run-up the count starts from stays the same length
                    new = f'{m.group(1)}{n[unit]}{m.group(3)}{max(0, n[unit] - lead)}{m.group(5)}{fmt(n[unit])}{m.group(7)}'
                    changes += new != m.group(0)
                    chunk = chunk[:m.start()] + new + chunk[m.end():]
        parts.append(chunk)
    for i, (unit, pat, pages) in enumerate(PHRASES):
        if name in pages and not hits[i]:
            errors.append(f'{name}: no match for /{pat}/ — a copy edit moved this phrase; update PHRASES')
    if name == 'about.html':
        for unit, cid, word in COUNTERS:
            if cid not in found:
                errors.append(f'{name}: the {word} counter (#{cid}) was not found')
    text = ''.join(parts)
    # anything that still looks like a library total and is not one
    for chunk, live in split(text):
        if not live:
            continue
        for m in GENERIC.finditer(chunk):
            unit = 'icons' if m.group(2).startswith('icon') else m.group(2)
            around = chunk[max(0, m.start() - 40):m.end() + 30].replace('\n', ' ')
            if m.group(1) == fmt(n[unit]) or any(a in around for a in ALLOW):
                continue
            errors.append(f'{name}: "{m.group(0)}" is not the library\'s {unit} count ({fmt(n[unit])}) and no pattern stamps it: …{around.strip()}…')
    return text, changes


def main():
    check = '--check' in sys.argv
    data = json.loads((SITE / 'icons.json').read_text())
    n = count(data)
    version = (data.get('meta') or {}).get('version', '?')
    declared = (data.get('meta') or {}).get('count')
    print(f'icons.json {version}: {fmt(n["icons"])} icons, {fmt(n["shapes"])} shapes, {fmt(n["keywords"])} keywords, {n["categories"]} categories')
    errors = []
    if declared is not None and declared != n['icons']:
        errors.append(f'icons.json: meta.count says {declared}, the file holds {n["icons"]} distinct icons')
    total, out = 0, {}
    for name in PAGES:
        path = SITE / name
        text = path.read_text()
        new, changes = stamp(name, text, n, errors)
        total += changes
        print(f'  {name}: {changes} number{"" if changes == 1 else "s"} {"out of date" if check else "to stamp"}')
        if new != text:
            out[path] = new
    if errors:
        print('\nERRORS (nothing was written):'); [print('  ' + e) for e in errors]
        sys.exit(1)
    if not check:
        for path, new in out.items():
            path.write_text(new)
    if check and total:
        print(f'\n{total} numbers are out of date: run  python3 .github/scripts/stamp-counts.py')
        sys.exit(1)
    print('\nall pages match the data' if not total else f'\n{total} numbers stamped')


if __name__ == '__main__':
    main()
