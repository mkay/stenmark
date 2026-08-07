# Translating Stenmark

Translations live in `po/`. Each language is one `.po` file named after its
locale code (`de.po`, `tr.po`, `fr.po` …).

## Who should translate

Please translate only into your **mother tongue**, or a language you genuinely
speak — not one you are running through a machine translator.

This isn't gatekeeping — it's the only part that can't be automated. Producing a
draft is trivial; anyone can paste `stenmark.pot` into a translation engine, and
so can I. What no machine and no non-speaker can do is tell whether the result
actually sounds like the language. Machine output reads plausibly while getting
the register wrong, mistranslating a term of art, or mangling a case ending —
and a user who meets that has no way to tell it's wrong. Plain English is the
better failure.

So the contribution isn't the text. It's you putting your name to it.

By all means start from a machine draft if it saves you typing — just leave the
entries `fuzzy` until you have read every one, which is exactly what the fuzzy
flag is for (see below).

## Tone

Stenmark addresses the user informally where the language makes that
distinction — German uses *du*, not *Sie*. Keep imperatives properly spelled
out (`Wähle`, `Klicke` — not `Wähl`, `Klick`): informal, not sloppy. Apply the
equivalent register in your own language.

## Adding a new language

```sh
meson setup builddir
ninja -C builddir stenmark-pot            # refresh po/stenmark.pot from the source
msginit --locale=tr --input=po/stenmark.pot --output=po/tr.po
```

Then add the code to `po/LINGUAS` (one per line, alphabetical), and add it to
`SUPPORTED_LANGUAGES` in `stenmark/i18n.py` with its name written in itself
(`("tr", "Türkçe")`) so it appears in the language menu in Preferences. A
language is only built and installed once it appears in `LINGUAS`.

## Updating an existing language

```sh
ninja -C builddir stenmark-pot
ninja -C builddir stenmark-update-po      # merge new strings into every .po
```

Strings whose English source changed are marked `#, fuzzy`. Fuzzy entries are
**not** shown to users — the English original is displayed instead — so an
unreviewed string can never reach the interface. Clear the flag once you have
checked the translation.

## Editing

Use [Poedit](https://poedit.net/) or GNOME's Gtranslator, or any text editor.

Placeholders like `{name}` and `{app}` may be moved anywhere in the sentence —
they are substituted by name, not position:

```po
msgid "Welcome to {app}"
msgstr "Willkommen bei {app}"
```

Do not rename or drop a placeholder; the application will fail to start that
string. Run `msgfmt --check po/xx.po -o /dev/null` to verify before submitting.

Counted strings have two entries; supply as many forms as your language needs:

```po
msgid "{n} document"
msgid_plural "{n} documents"
msgstr[0] "{n} Dokument"
msgstr[1] "{n} Dokumente"
```

A few strings carry markup that must survive translation — the welcome text
has an `<a href="create">…</a>` link. Keep the tag; move it wherever the
sentence needs it.

## Testing

```sh
LANGUAGE=de stenmark
```

Or pick the language in Preferences → General → Appearance → Language, which
writes it to `~/.config/stenmark/settings.json` and takes effect on restart.

## Credit

Translate the string `translator-credits` with your name and it will appear in
the About dialog. Untranslated, it stays hidden.

## Submitting

Open a pull request with your `.po` file (plus the `po/LINGUAS` and
`stenmark/i18n.py` lines if the language is new). Anything you have not read
yourself should still be marked fuzzy — see
[Who should translate](#who-should-translate).
