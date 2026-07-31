#!/usr/bin/env bash
#
# Detach-sign every built package and rebuild the repository database so that it
# records the signatures. Run after scripts/build.sh, as the user whose GPG
# keyring holds the signing key.
#
#   SIGNING_KEY=0xDEADBEEF ./scripts/sign.sh
#
# This is separate from build.sh because the two cannot share a user: makepkg
# refuses to run as root, while in CI the key is imported into root's keyring.

set -euo pipefail

REPO_NAME=android-cuttlefish
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${ROOT}/dist"

: "${SIGNING_KEY:?set SIGNING_KEY to the GPG key id to sign with}"

for package in "${DIST}"/*.pkg.tar.zst; do
  echo "==> signing $(basename "${package}")"
  # --no-armor: pacman expects a binary detached signature at <package>.sig.
  # --yes: overwrite on a re-run rather than prompting.
  gpg --batch --yes --detach-sign --no-armor \
    --local-user "${SIGNING_KEY}" "${package}"
done

# Rebuilt from scratch so the database records the signatures that did not exist
# when build.sh first assembled it. --include-sigs stores each package's
# signature in the database, so pacman knows to expect one.
echo "==> re-assembling ${REPO_NAME}.db with signatures"
rm -f "${DIST}/${REPO_NAME}".{db,files}*
repo-add --sign --key "${SIGNING_KEY}" --include-sigs \
  "${DIST}/${REPO_NAME}.db.tar.gz" "${DIST}"/*.pkg.tar.zst

# repo-add leaves .db, .files and their .sig files as symlinks to the tarballs.
# GitHub release assets cannot be symlinks, so replace them with real files.
for link in "${DIST}/${REPO_NAME}".{db,files}{,.sig}; do
  [ -L "${link}" ] || continue
  target="$(readlink -f "${link}")"
  rm "${link}"
  cp "${target}" "${link}"
done

echo "==> dist/"
ls -la "${DIST}"
