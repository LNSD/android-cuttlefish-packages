# Cuttlefish packages for Arch Linux

An Arch/Manjaro pacman repository for [Cuttlefish][cf], Android's configurable
virtual device. Upstream ships Debian packages only; these repackage the
official `.deb`s so `pacman` and `pamac` can install and update them normally.

[cf]: https://github.com/google/android-cuttlefish

## Install

Add to `/etc/pacman.conf`:

```ini
[cuttlefish]
SigLevel = Optional TrustAll
Server = https://github.com/LNSD/android-cuttlefish-packages/releases/latest/download
```

Then:

```sh
sudo pacman -Sy cuttlefish-base-bin cuttlefish-user-bin
sudo usermod -aG cvdnetwork "$USER"      # log out and back in
sudo systemctl enable --now cuttlefish-host-resources.service
```

`releases/latest/download` always resolves to the newest release, so the URL
never needs updating. Each release is self-contained: its `cuttlefish.db`
indexes exactly the packages published beside it.

> `SigLevel = Optional TrustAll` accepts unsigned packages. Signing would need a
> key distributed out of band — see [Signing](#signing).

## Why repackaging is sound

The upstream `.deb` declares 40+ dependencies, six of them `-dev` packages at
runtime, which normally means linkage against unversioned `.so` symlinks and
makes cross-distribution repackaging fragile.

It is not the case here. `DT_NEEDED` across **all 80 shipped ELF objects**
resolves to only:

| soname | Arch package |
|---|---|
| `libc.so.6`, `libm.so.6`, `ld-linux-x86-64.so.2` | `glibc` |
| `libgcc_s.so.1` | `gcc-libs` |
| `liblzma.so.5` | `xz` |
| `libopus.so.0` | `opus` |

Everything else is statically linked, including the bundled software Vulkan
renderer (`libvk_swiftshader.so`). The rest of the Debian `Depends:` field is
runtime *tooling* — `dnsmasq`, `iptables`, `nftables`, `jq`, `python3` — which
maps directly onto Arch packages. Debian's `libc6 (>= 2.36)` floor is satisfied
by any current Arch, glibc symbol versioning being forward-compatible.

One exception: Debian's `bridge-utils` is dropped. It no longer exists in the
Arch repositories, and nothing in the payload calls `brctl` — bridges are made
with `ip link add`, and the `bridge` kernel module is `modprobe`'d directly.

### What the packaging changes

| Upstream (Debian) | Here (Arch) |
|---|---|
| `/lib/systemd/system/` | `/usr/lib/systemd/system/` |
| `/lib/udev/rules.d/` | `/usr/lib/udev/rules.d/` |
| `/etc/init.d/*` (SysV) | `/usr/lib/cuttlefish-common/init/`, with the units repointed |
| `/usr/share/doc/`, `/usr/share/lintian/` | dropped; `copyright` moves to `/usr/share/licenses/` |
| `postinst`: `addgroup --system cvdnetwork` | `sysusers.d` |
| `postinst`: `adduser --system _cutf-operator` | `sysusers.d` |
| `postinst`: `setcap` on two binaries | `.install` `post_install()` |
| `postinst`: `modprobe` loop | `modules-load.d`, which Arch reads natively |

The SysV scripts are relocated rather than deleted: both systemd units are
`dh_installinit` wrappers whose `ExecStart` *is* the init script, so dropping
them leaves the units pointing at nothing. They also source
`/lib/lsb/init-functions`, which Arch does not ship — but call none of its
functions, so that line is removed.

`setcap` cannot move into `package()`: `makepkg` builds under `fakeroot`, which
does not implement the `security.capability` xattr.

## Naming

Packages are suffixed `-bin` per Arch convention, because they repackage
prebuilt binaries rather than building from source. They `provide` the
unsuffixed name and `conflict` with both it and a `-git` variant, so a
source-built package can coexist in the repository later without ambiguity.

## Updating

[Renovate][rn] watches Google's apt repository through its `deb` datasource and
opens a pull request when a new version appears.

[rn]: https://docs.renovatebot.com/

Two PKGBUILD fields are *not* functions of `pkgver` and so cannot be templated:

- `_debhash` — Artifact Registry appends an opaque hash to every filename, so
  the download URL cannot be derived from the version.
- `sha256sums[0]` — the checksum of the `.deb`.

`scripts/resolve-deb.py` resolves both from the upstream package index and
verifies the checksum against the actual downloaded bytes.

Renovate runs as the **Mend GitHub App**, configured by
`.github/renovate.json5`. The app cannot run the resolver itself —
`postUpgradeTasks.commands` are validated against `allowedCommands`, a
self-hosted-only admin option — so the flow is:

1. Renovate opens a pull request bumping `pkgver`.
2. `renovate-fixup.yml` runs the resolver on that branch and commits the
   resulting `_debhash` and checksum.
3. `check.yml` re-runs the resolver with `--check`, and builds and installs the
   packages. A bump that skipped step 2 fails here rather than being merged.
4. Merging to `main` triggers `release.yml`, which rebuilds and publishes.

Step 2 pushes with a PAT (`RENOVATE_FIXUP_TOKEN`), because pushes made with
`GITHUB_TOKEN` do not trigger workflows — step 3 would otherwise never re-run.

## Building locally

```sh
./scripts/build.sh          # -> dist/ with packages and cuttlefish.db
```

Needs `base-devel`. `makepkg` must not run as root.

## Signing, SBOM and provenance

All three are produced automatically by `release.yml`. Nothing is signed or
attested by hand.

**Packages and the database are GPG-signed** with a signing-only subkey of
`Lorenzo Delgado <lnsdev@proton.me>`, held as a repository secret. `sign.sh`
detach-signs each package and rebuilds the database with `--include-sigs`, so
pacman knows to expect a signature.

Signing is separate from `build.sh` because the two cannot share a user:
`makepkg` refuses to run as root, while CI imports the key into root's keyring.

To verify signatures, trust the key once, then tighten `SigLevel`:

```sh
sudo pacman-key --recv-keys 82E8BBCA46EBA55621A7C12548A5470E1E3E8BA7
sudo pacman-key --lsign-key 82E8BBCA46EBA55621A7C12548A5470E1E3E8BA7
```

```ini
[cuttlefish]
SigLevel = Required DatabaseOptional
Server = https://github.com/LNSD/android-cuttlefish-packages/releases/latest/download
```

The bootstrap is unavoidably circular — signature checking cannot validate the
key that enables it. devkitPro solves this with a `devkitpro-keyring` package
installed out of band; the manual `pacman-key` route above is the lighter
equivalent.

**Provenance** is attested with `actions/attest-build-provenance`, using
Sigstore keyless signing — no key, no secret:

```sh
gh attestation verify cuttlefish-base-bin-*.pkg.tar.zst \
  --repo LNSD/android-cuttlefish-packages
```

This attests that the artifact was built by this workflow, from this commit. It
says **nothing** about Google's binaries inside it — that link is the `.deb`
checksum, verified against the upstream index by `resolve-deb.py`.

**An SBOM** (`cuttlefish.spdx.json`) is generated with syft and attested with
`actions/attest-sbom`.

> [!NOTE]
> The SBOM is necessarily partial. syft reads Go module metadata out of the Go
> components (`host_orchestrator`, `operator`), which produces a real dependency
> list. The C++ components (`cvd`, `webRTC`, …) are statically linked, so what
> was compiled into them is invisible to any scanner. A complete SBOM could only
> come from Google.

## Licence

The packaging in this repository — the PKGBUILDs, scripts and workflows — is
dual-licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT License ([LICENSE-MIT](LICENSE-MIT))

at your option.

The **packaged software is Google's**, under Apache-2.0. This repository
redistributes the official binaries unmodified except for the path relocations
described above, and is not affiliated with or endorsed by Google.

### Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted
for inclusion in the work by you, as defined in the Apache-2.0 licence, shall be
dual-licensed as above, without any additional terms or conditions.
