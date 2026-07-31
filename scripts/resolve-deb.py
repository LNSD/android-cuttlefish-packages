#!/usr/bin/env python3
"""Fill in the .deb filename hash and checksum for the pkgver already in place.

Renovate bumps `pkgver` from Google's apt index, but two fields in a PKGBUILD
are not functions of the version and so cannot be templated:

  _debhash      Artifact Registry appends an opaque hash to every filename.
  sha256sums[0] the checksum of the .deb itself.

This reads the upstream package index, finds the entry matching each PKGBUILD's
current pkgver, and rewrites those two fields. Run after any pkgver change --
Renovate does so via postUpgradeTasks, and it is safe to run by hand.

    ./scripts/resolve-deb.py [--check]

--check reports what would change and exits non-zero if anything is stale,
without writing. Used by CI to fail a hand-edited PR that forgot to run this.
"""

import argparse
import hashlib
import pathlib
import re
import sys
import urllib.request

REPO = "https://us-apt.pkg.dev/projects/android-cuttlefish-artifacts"
INDEX = f"{REPO}/dists/android-cuttlefish/main/binary-amd64/Packages"

PACKAGES_DIR = pathlib.Path(__file__).resolve().parent.parent / "packages"


def fetch_index():
    """Return {(package, version): {field: value}} for every amd64 entry."""
    with urllib.request.urlopen(INDEX, timeout=60) as response:
        text = response.read().decode("utf-8", "replace")

    entries = {}
    for stanza in text.split("\n\n"):
        fields = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", stanza, re.MULTILINE))
        if fields.get("Architecture") != "amd64" or "Package" not in fields:
            continue
        entries[(fields["Package"], fields["Version"])] = fields
    return entries


def pkgbuild_field(text, name):
    match = re.search(rf"^{name}=['\"]?([^'\"\n]+)", text, re.MULTILINE)
    return match.group(1) if match else None


def download_sha256(url):
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=900) as response:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report staleness and exit non-zero; do not write",
    )
    args = parser.parse_args()

    index = fetch_index()
    stale = []

    # Only the -bin packages pin a .deb. The -git recipes build from source and
    # carry a git-describe version that is not in any apt index.
    for pkgbuild in sorted(PACKAGES_DIR.glob("*-bin/PKGBUILD")):
        text = pkgbuild.read_text()
        debpkg = pkgbuild_field(text, "_debpkg")
        pkgver = pkgbuild_field(text, "pkgver")

        fields = index.get((debpkg, pkgver))
        if fields is None:
            sys.exit(f"{pkgbuild}: {debpkg} {pkgver} is not in the upstream index")

        # Filenames look like: cuttlefish-base_1.55.1_amd64_<hash>.deb
        want_hash = fields["Filename"].rsplit("_", 1)[-1].removesuffix(".deb")
        have_hash = pkgbuild_field(text, "_debhash")

        want_sha = fields["SHA256"]
        have_sha = re.search(r"^  '([0-9a-f]{64})'$", text, re.MULTILINE).group(1)

        if (want_hash, want_sha) == (have_hash, have_sha):
            print(f"{debpkg} {pkgver}: up to date")
            continue

        stale.append(f"{debpkg} {pkgver}")
        if args.check:
            print(f"{debpkg} {pkgver}: STALE (_debhash and/or sha256sums)")
            continue

        # Trust the index only after confirming it against the actual bytes:
        # this checksum is the sole integrity gate on the download.
        url = f"{REPO}/{fields['Filename']}"
        print(f"{debpkg} {pkgver}: verifying {url}", file=sys.stderr)
        actual = download_sha256(url)
        if actual != want_sha:
            sys.exit(f"  checksum mismatch: index {want_sha}, download {actual}")

        text = re.sub(
            r"^_debhash=.*$", f"_debhash='{want_hash}'", text, flags=re.MULTILINE
        )
        text = re.sub(
            r"^  '[0-9a-f]{64}'$", f"  '{want_sha}'", text, count=1, flags=re.MULTILINE
        )
        pkgbuild.write_text(text)
        print(f"{debpkg} {pkgver}: updated")

    if args.check and stale:
        sys.exit(f"stale PKGBUILDs: {', '.join(stale)} -- run scripts/resolve-deb.py")


if __name__ == "__main__":
    main()
