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

- Typewriter mode keeps the line you are writing centred in the window, with room to scroll past the end of the document. Turn it on in Preferences → Editor, from the status bar while editing, or with Ctrl+Shift+T.
- The root folder picker drills down one level at a time instead of listing every folder at once. Click a folder to make it the root, or the arrow beside it to see what is inside.
- Changing the root folder starts fresh in the folder you picked, rather than carrying on listing documents from the one you left.
- The sidebar highlights only what you actually chose. Creating a file no longer moves the highlight away from the folder you were in.
- Translators are credited in About in every language, not only in the one they translated.
