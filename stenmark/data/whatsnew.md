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

- Editing now starts where you were reading. Double-click any text and the editor opens with the caret on that very word; switch back and the reader returns to the line you were editing.
- The sidebar steps out of the way while you edit, so the editor and preview get the whole window. It comes back exactly as you left it.
- Esc leaves edit mode and saves. If the editor's find panel is open, the first Esc closes that instead.
- Both new habits can be turned off under Preferences → Editor → Behaviour.
