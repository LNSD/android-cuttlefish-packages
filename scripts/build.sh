#!/usr/bin/env bash
#
# Build every package and assemble a pacman repository database from the
# results. Used by .github/workflows/release.yml and runnable locally.
#
#   ./scripts/build.sh          -> dist/ containing packages + cuttlefish.db
#
# makepkg refuses to run as root, so run this as a normal user with sudo rights
# (or, in CI, as the unprivileged build user the workflow creates).

set -euo pipefail

REPO_NAME=cuttlefish
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${ROOT}/dist"

rm -rf "${DIST}"
mkdir -p "${DIST}"

for pkgbuild in "${ROOT}"/packages/*/PKGBUILD; do
  pkgdir="$(dirname "${pkgbuild}")"
  echo "==> building $(basename "${pkgdir}")"
  # --nodeps: dependencies are Arch runtime packages we do not need present in
  # order to repackage a prebuilt binary payload.
  (cd "${pkgdir}" && makepkg --clean --force --nodeps --skippgpcheck)
  mv "${pkgdir}"/*.pkg.tar.zst "${DIST}/"
done

echo "==> assembling ${REPO_NAME}.db"
repo-add "${DIST}/${REPO_NAME}.db.tar.gz" "${DIST}"/*.pkg.tar.zst

# repo-add leaves .db and .files as symlinks to the tarballs. GitHub release
# assets cannot be symlinks, so replace them with real files.
for link in "${DIST}/${REPO_NAME}.db" "${DIST}/${REPO_NAME}.files"; do
  [ -L "${link}" ] || continue
  target="$(readlink -f "${link}")"
  rm "${link}"
  cp "${target}" "${link}"
done

echo "==> dist/"
ls -la "${DIST}"
