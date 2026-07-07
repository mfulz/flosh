# Arch packaging

This directory contains the release PKGBUILD template for the AUR package
`flosh`.

Release flow:

```bash
# from the repository root
git tag -a v0.1.0 -m 'flosh 0.1.0'
git push origin v0.1.0

cd packaging/arch
updpkgsums
makepkg --printsrcinfo > .SRCINFO
makepkg -Csf
namcap PKGBUILD ./*.pkg.tar.*
```

AUR publish flow, from a separate AUR checkout:

```bash
git clone ssh://aur@aur.archlinux.org/flosh.git /tmp/aur-flosh
cp PKGBUILD .SRCINFO /tmp/aur-flosh/
cd /tmp/aur-flosh
git add PKGBUILD .SRCINFO
git commit -m 'Initial import: flosh 0.1.0'
git push
```

For aurutils, build from the AUR checkout after copying the files:

```bash
aur build -r
```

Before publishing, replace `sha256sums=('SKIP')` by running `updpkgsums` after the
tag exists on GitHub.
