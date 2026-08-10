# Maintainer: Kreuder <mk@singular.de>
pkgname=stenmark
pkgver=0.7.0
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
sha256sums=('dcecdea6b3a54345afecb0a24b4d30025a8e1bd5d43a5cd5627c20289c2d5609')

build() {
  arch-meson "$pkgname-$pkgver" build
  meson compile -C build
}

package() {
  meson install -C build --destdir "$pkgdir"
  install -Dm644 "$pkgname-$pkgver/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 "$pkgname-$pkgver/COPYRIGHT" "$pkgdir/usr/share/licenses/$pkgname/COPYRIGHT"
}
