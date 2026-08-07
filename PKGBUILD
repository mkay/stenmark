# Maintainer: Kreuder <mk@singular.de>
pkgname=stenmark
pkgver=0.6.1
pkgrel=1
pkgdesc='Your markdown librarian. A GTK4 Markdown reader, organizer and editor'
arch=('any')
url='https://github.com/mkay/stenmark'
license=('GPL-3.0-only')
depends=(
  'python'
  'python-gobject'
  'python-markdown'
  'python-pygments'
  'python-yaml'
  'gtk4'
  'libadwaita'
  'webkitgtk-6.0'
)
conflicts=('marklite')
replaces=('marklite')
makedepends=(
  'meson'
  'gettext'
)
source=("$pkgname-$pkgver.tar.gz::https://github.com/mkay/stenmark/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('229361b618a1c67b1f40544a22b44b0d389800408959a62fdcaf3d3c42dd6f59')

build() {
  arch-meson "$pkgname-$pkgver" build
  meson compile -C build
}

package() {
  meson install -C build --destdir "$pkgdir"
  install -Dm644 "$pkgname-$pkgver/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 "$pkgname-$pkgver/COPYRIGHT" "$pkgdir/usr/share/licenses/$pkgname/COPYRIGHT"
}
