# Cuttlefish packages for Arch Linux

An Arch/Manjaro pacman repository for [Cuttlefish][cf], Android's configurable
virtual device. Upstream ships Debian packages only; these repackage the
official `.deb`s so `pacman` and `pamac` can install and update them normally.

[cf]: https://github.com/google/android-cuttlefish

## Install

Add to `/etc/pacman.conf`:

```ini
[android-cuttlefish]
SigLevel = Required TrustAll
Server = https://github.com/LNSD/android-cuttlefish-packages/releases/latest/download
```

Then:

```sh
sudo pacman -Sy cuttlefish-base-bin cuttlefish-user-bin
sudo usermod -aG cvdnetwork "$USER"      # log out and back in
sudo systemctl enable --now cuttlefish-host-resources.service
```

The signing key is published on `keyserver.ubuntu.com`, which is pacman's
default, so pacman offers to import it during that first install:

```
:: Import PGP key 6B6480C55419E90D, "Lorenzo Delgado <lnsdev@proton.me>"? [Y/n]
```

`TrustAll` is what makes the imported key acceptable: under pacman's default
`TrustedOnly`, a key that was merely imported still has unknown trust and the
install fails despite the prompt.

<details>
<summary>Or trust the key explicitly, without <code>TrustAll</code></summary>

`TrustAll` tells pacman to accept a signature from *any* key in its keyring for
this repository, not only this one. To pin trust to this key specifically, add
it by hand instead. The key ships in this repository, so no keyserver is
involved:

```sh
curl -fsSL https://raw.githubusercontent.com/LNSD/android-cuttlefish-packages/main/keys/lnsdev.asc \
  | sudo pacman-key --add -
sudo pacman-key --lsign-key 82E8BBCA46EBA55621A7C12548A5470E1E3E8BA7
```

Then use the stricter setting in the stanza above:

```ini
SigLevel = Required DatabaseOptional
```

</details>

`releases/latest/download` always resolves to the newest release, so the URL
never needs updating. Each release is self-contained: its `android-cuttlefish.db`
indexes exactly the packages published beside it.

Every release is signed, carries an SBOM, and has a provenance attestation. See
[Signing, SBOM and provenance](#signing-sbom-and-provenance).

## Packages

| Package | Source | Published here |
|---|---|---|
| `cuttlefish-base-bin` | Google's official `.deb` | yes |
| `cuttlefish-user-bin` | Google's official `.deb` | yes |
| `cuttlefish-base-git` | upstream git HEAD, built with bazel | no |
| `cuttlefish-user-git` | upstream git HEAD, Go + web UI | no |

The `-bin` suffix is the Arch convention for repackaged prebuilt binaries.
Each package `provides` the unsuffixed name and `conflicts` with the other
variant, so exactly one can be installed.

**Only the `-bin` packages are published** in the pacman repository. The `-git`
recipes are for building upstream HEAD locally:

```sh
cd packages/cuttlefish-base-git && makepkg -si
```

They are not published because a `-git` version changes with every upstream
commit, so a prebuilt snapshot would be stale the moment it was built, and
`cuttlefish-base-git` is a large bazel C++ build.

Both `-git` recipes mirror upstream's `debian/rules` minus debhelper: the same
bazel and Go invocations, then the file mapping from the corresponding
`debian/*.install` and `*.links` applied directly, with the same Arch path
relocations as the `-bin` packages.

> [!NOTE]
> The `-git` recipes are **not built in CI** and have not been built end to end
> here. `cuttlefish-base-git` needs bazel to compile a large C++ tree, which
> does not fit a standard GitHub runner. Treat them as a documented starting
> point rather than a tested build.

## Repackaging

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
runtime *tooling* (`dnsmasq`, `iptables`, `nftables`, `jq`, `python3`), which
maps directly onto Arch packages. Debian's `libc6 (>= 2.36)` floor is satisfied
by any current Arch, glibc symbol versioning being forward-compatible.

One exception: Debian's `bridge-utils` is dropped. It no longer exists in the
Arch repositories, and nothing in the payload calls `brctl`: bridges are made
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
`/lib/lsb/init-functions`, which Arch does not ship, but call none of its
functions, so that line is removed.

`setcap` cannot move into `package()`: `makepkg` builds under `fakeroot`, which
does not implement the `security.capability` xattr.

## Updating

Updates are automated end to end:

1. [Renovate][rn] watches [upstream's GitHub releases][up] and opens a pull
   request bumping `pkgver`.
2. `renovate-fixup.yml` runs `scripts/resolve-deb.py`, which fills in the two
   fields that cannot be derived from a version: the `.deb` filename hash and
   its checksum.
3. `check.yml` builds the packages and installs them into a clean container.
4. Merging to `main` triggers `release.yml`, which rebuilds and publishes.

[rn]: https://docs.renovatebot.com/
[up]: https://github.com/google/android-cuttlefish/releases

See [`.github/renovate.json5`](.github/renovate.json5) for why the release feed
rather than the apt repository, and
[`renovate-fixup.yml`](.github/workflows/renovate-fixup.yml) for why step 2 is a
workflow rather than a Renovate `postUpgradeTask`.

## Signing, SBOM and provenance

All three are produced automatically by `release.yml`. Nothing is signed or
attested by hand.

**Packages and the database are GPG-signed** with a signing-only subkey of
`Lorenzo Delgado <lnsdev@proton.me>`, held as the `GPG_SIGNING_KEY` repository
secret. `sign.sh` detach-signs each package and rebuilds the database with
`--include-sigs`, so pacman knows to expect a signature.

Signing runs in `sign.sh`, separately from `build.sh`, because `makepkg` must
not run as root.

The public key is committed at [`keys/lnsdev.asc`](keys/lnsdev.asc) and is the
recommended way to obtain it, as shown under [Install](#install). It is also on
`keyserver.ubuntu.com`.

> [!NOTE]
> `keys.openpgp.org` is **not** a usable source for it. That server strips user
> IDs until the address is verified by email, and gpg skips a key with no user
> ID (`new key but contains no user ID - skipped`), so `pacman-key --recv-keys`
> against it fails.

```ini
[android-cuttlefish]
SigLevel = Required DatabaseOptional
Server = https://github.com/LNSD/android-cuttlefish-packages/releases/latest/download
```

The bootstrap is unavoidably circular: signature checking cannot validate the
key that enables it. devkitPro solves this with a `devkitpro-keyring` package
installed out of band; the manual `pacman-key` route above is the lighter
equivalent.

**Provenance** is attested with `actions/attest-build-provenance`, using
Sigstore keyless signing, so there is no key and no secret:

```sh
gh attestation verify cuttlefish-base-bin-*.pkg.tar.zst \
  --repo LNSD/android-cuttlefish-packages
```

This attests that the artifact was built by this workflow, from this commit. It
says **nothing** about Google's binaries inside it. That link is the `.deb`
checksum, verified against the upstream index by `resolve-deb.py`.

**An SBOM** (`android-cuttlefish.spdx.json`) is generated with syft and attested with
`actions/attest-sbom`.

> [!NOTE]
> The SBOM is necessarily partial. syft reads Go module metadata out of the Go
> components (`host_orchestrator`, `operator`), which produces a real dependency
> list. The C++ components (`cvd`, `webRTC`, …) are statically linked, so what
> was compiled into them is invisible to any scanner. A complete SBOM could only
> come from Google.

## License

The packaging in this repository (the PKGBUILDs, scripts and workflows) is
dual-licensed under either of

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))
- MIT License ([LICENSE-MIT](LICENSE-MIT))

at your option.

The **packaged software is Google's**, under Apache-2.0. This repository
redistributes the official binaries unmodified except for the path relocations
described above, and is not affiliated with or endorsed by Google.

### Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted
for inclusion in the work by you, as defined in the Apache-2.0 license, shall be
dual-licensed as above, without any additional terms or conditions.
