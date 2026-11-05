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

- Safer saving: Stenmark asks before overwriting a note that changed on disk, and before closing with unsaved edits.
- Discard really discards, undo stays inside the current note, and failed saves and file operations now say so.
- Notes can no longer run scripts or load anything from the network, so remote images don't show.
- A new Markdown engine fixes many lists, strikethrough and task checkboxes. Headings now need a space after the #.
- Renames and moves keep pins, copying code keeps every line, and the sidebar tint can be turned off in Preferences.
