<!--
Release notes for the CURRENT version only. Shown once on the first launch after an
update, and reachable again from the About dialog. Curated by hand — nothing here is
generated from git history, so rewrite it whenever the version in meson.build is
bumped.

English only, deliberately: these notes do not go through gettext, so they stay in
English regardless of the language setting. Keep them to short bullets — five one- or
two-line bullets is what the dialog holds without scrolling. Don't write the version
number here; the dialog takes it from the build.

Cover everything since the last *released* version, not just the last session's work.
The released version is what AUR shows, which can be several sessions behind main:
  git log $(git tag --sort=-version:refname | head -1)..HEAD --oneline

Blank lines and this comment are ignored. Every other line is one bullet; a leading
"-", "*" or "•" is optional and stripped.

Links may be written as [label](https://…) or as a bare URL. Prefer the labelled
form: a full URL wraps mid-scheme in a dialog this narrow.
-->

- On first launch Stenmark asks which folder your notes live in, instead of quietly starting in ~/Documents.
- Stenmark no longer fails to start when the notes folder has no subfolders in it.
- Selecting text with the mouse in typewriter mode no longer sends the document racing past you.
