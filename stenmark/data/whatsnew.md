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

- Safer saving for synced notes. If a note changes on disk while you edit it, Stenmark now asks instead of overwriting it, and it tells you when a save fails. Discard really discards, and closing or quitting asks about unsaved edits.
- Undo stays inside the note you're editing. Files are written atomically, and keep their encoding and line endings.
- Notes can no longer run scripts or load anything from the network, so remote images don't show.
- A new Markdown engine fixes lists after a paragraph, code blocks in lists, loose task lists, list numbering and strikethrough. Checkboxes and the table of contents now find the exact line. A heading needs a space after the #: "###Title" is plain text now.
- Renames and moves keep pins, failed file operations say so, and copying code keeps every line. The sidebar list has a light accent tint, which Preferences can turn off.
