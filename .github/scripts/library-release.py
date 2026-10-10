#!/usr/bin/env python3
"""Bring a new library release onto the site.

The library publishes a small version.json beside its icons.json. This script reads it, and when its
version is HIGHER than the icons.json committed here, it:

  1. downloads the release's icons.json from the tag-pinned address version.json hands over;
  2. checks the file is what version.json says it is: same version, same icon, shape, keyword and
     category counts (counted here, from the file itself);
  3. replaces icons.json and stamps the counts into the pages (stamp-counts.py).

The pages read the version number, the category counts, the About counters, the green dots and the
release card from icons.json when they load, so replacing the file moves all of those. The stamp covers
what scripts cannot reach: titles, descriptions, link previews and the press text.

It never commits: the workflow does, and only when this script says something changed.

Safe by construction:
  - only ever moves UP. raw.githubusercontent.com caches for a few minutes and its edges can disagree,
    so an old version.json must never roll the site back;
  - one failed check and nothing on disk changes (exit 1, the workflow run turns red, GitHub emails);
  - a release whose tag has not reached the CDN yet is simply picked up by the next run.

Run by hand from the site folder:   python3 .github/scripts/library-release.py
"""
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
SITE = pathlib.Path(os.environ.get('SITE_DIR') or HERE.parents[1])
# both can be pointed elsewhere for a test; the workflow never sets them
VERSION_URL = os.environ.get('LIBRARY_VERSION_URL', 'https://raw.githubusercontent.com/iconoteka/iconoteka/main/version.json')
ICONS_PREFIX = os.environ.get('LIBRARY_ICONS_PREFIX', 'https://cdn.jsdelivr.net/gh/iconoteka/iconoteka@')
VERSION_RX = re.compile(r'^\d{2}\.\d{2}\.\d{2}$')
MAX_DROP = 0.10   # a release may retire icons, but one that loses more than a tenth of the library is a broken build

spec = importlib.util.spec_from_file_location('stamp_counts', HERE / 'stamp-counts.py')
stamp_counts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stamp_counts)


def fetch(url):
    """The body, or None when the address does not exist (yet)."""
    req = urllib.request.Request(url, headers={'User-Agent': 'iconoteka.com library-release'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except urllib.error.URLError as e:
        if isinstance(e.reason, FileNotFoundError):   # a file:// address in a test
            return None
        raise


def key(version):
    return tuple(int(x) for x in version.split('.'))


def result(changed, message=''):
    out = os.environ.get('GITHUB_OUTPUT')
    if out:
        with open(out, 'a') as f:
            f.write(f'changed={"true" if changed else "false"}\nmessage={message}\n')


def stop(why):
    print('ERROR: ' + why)
    result(False)
    sys.exit(1)


def main():
    path = SITE / 'icons.json'
    old_bytes = path.read_bytes()
    old = json.loads(old_bytes)
    have = old['meta']['version']

    body = fetch(VERSION_URL)
    if body is None:
        print(f'no version.json at {VERSION_URL} yet; the site stays on {have}')
        return result(False)
    v = json.loads(body)
    want = str(v.get('version', ''))
    if not VERSION_RX.match(want):
        stop(f'version.json has no usable version: {want!r}')
    if key(want) <= key(have):
        print(f'library {want}, site {have}: nothing to do')
        return result(False)

    url = str(v.get('icons', ''))
    if not url.startswith(ICONS_PREFIX + want + '/'):
        stop(f'version.json points at {url!r}; expected {ICONS_PREFIX}{want}/…')
    print(f'library {want} is newer than the site\'s {have}; downloading {url}')
    new_bytes = fetch(url)
    if new_bytes is None:
        print('the release file is not on the CDN yet; the next run picks it up')
        return result(False)

    new = json.loads(new_bytes)
    if new.get('meta', {}).get('version') != want:
        stop(f'the downloaded file says version {new.get("meta", {}).get("version")!r}, version.json says {want}')
    n = stamp_counts.count(new)
    for unit, field in (('icons', 'count'), ('shapes', 'shapes'), ('keywords', 'keywords'), ('categories', 'categories')):
        if v.get(field) != n[unit]:
            stop(f'{unit}: the file holds {n[unit]:,}, version.json says {v.get(field)!r}')
    before = stamp_counts.count(old)
    if n['icons'] < before['icons'] * (1 - MAX_DROP):
        stop(f'the release holds {n["icons"]:,} icons, the site has {before["icons"]:,}: too large a drop to take without a person looking')

    path.write_bytes(new_bytes)
    run = subprocess.run([sys.executable, str(HERE / 'stamp-counts.py')], env={**os.environ, 'SITE_DIR': str(SITE)})
    if run.returncode:
        path.write_bytes(old_bytes)   # the stamp wrote nothing; put the data back too
        stop('the stamp failed, so icons.json was put back and nothing changed')

    message = f'Library {want}: {n["icons"]:,} icons, {n["shapes"]:,} shapes'
    print('\n' + message)
    result(True, message)


if __name__ == '__main__':
    main()
