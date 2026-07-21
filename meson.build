project('stenmark',
  version: '0.5.1',
  meson_version: '>= 0.62.0',
  default_options: ['warning_level=2'],
)

python = import('python').find_installation('python3')
gnome = import('gnome')

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')

pkgdatadir = datadir / meson.project_name()
moduledir = pkgdatadir / 'stenmark'

conf = configuration_data()
conf.set('PYTHON', python.full_path())
conf.set('VERSION', meson.project_version())
conf.set('pkgdatadir', pkgdatadir)
conf.set('BIN', bindir / meson.project_name())

subdir('data')
subdir('stenmark')
subdir('bin')

gnome.post_install(
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
