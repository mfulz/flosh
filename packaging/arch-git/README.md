# Arch git packaging

Development/VCS package for installing the current git state as `flosh-git`.

This package intentionally follows the repository directly and does not require
release tags before testing on Arch.

Usage with a local PKGBUILD checkout:

```bash
cd packaging/arch-git
makepkg -Csf
sudo pacman -U flosh-git-*.pkg.tar.*
```

Regenerate `.SRCINFO` on a real Arch host before publishing to the AUR:

```bash
makepkg --printsrcinfo > .SRCINFO
```

AUR publish flow:

```bash
git clone ssh://aur@aur.archlinux.org/flosh-git.git /tmp/aur-flosh-git
cp PKGBUILD .SRCINFO /tmp/aur-flosh-git/
cd /tmp/aur-flosh-git
git add PKGBUILD .SRCINFO
git commit -m 'Initial import: flosh-git'
git push
```

For aurutils:

```bash
aur build -r
```
