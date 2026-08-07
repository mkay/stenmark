# Two stages: configure_file resolves @BIN@, then merge_file folds in the
# translations for Name / Comment / Keywords from po/.
desktop_in = configure_file(
  input: 'de.singular.stenmark.desktop.in.in',
  output: 'de.singular.stenmark.desktop.in',
  configuration: conf,
)

desktop_file = i18n.merge_file(
  input: desktop_in,
  output: 'de.singular.stenmark.desktop',
  type: 'desktop',
  po_dir: meson.project_source_root() / 'po',
  install: true,
  install_dir: datadir / 'applications',
)

metainfo_file = i18n.merge_file(
  input: 'de.singular.stenmark.metainfo.xml.in',
  output: 'de.singular.stenmark.metainfo.xml',
  type: 'xml',
  po_dir: meson.project_source_root() / 'po',
  install: true,
  install_dir: datadir / 'metainfo',
)

install_data(
  'de.singular.stenmark.svg',
  install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps',
)

install_data(
  'de.singular.stenmark-symbolic.svg',
  install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps',
)
