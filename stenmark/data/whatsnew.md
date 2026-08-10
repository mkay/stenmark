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
- Esc leaves edit mode and saves. Typing a backtick first no longer swallows it — a pending dead key used to eat the next Escape, Backspace or Return.
- The sidebar steps out of the way while you edit, giving the editor and preview the whole window. Both new habits can be switched off under Preferences → Editor → Behaviour.
- 48 editor themes — Dracula, Nord, Gruvbox, Tokyo Night, VS Code, Solarized — with a colour preview beside the picker.
- Preferences opens in a window of its own, so nothing dims the editor while you try a theme on. The window size setting has moved in there too.
