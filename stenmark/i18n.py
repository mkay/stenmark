# SPDX-License-Identifier: GPL-3.0-or-later

"""Translation helpers.

Every user-facing string goes through `_()` (or `ngettext()` for anything
counted, `C_()` where the same English word needs different translations in
different places). Import them from here rather than installing `_` into
builtins, so the dependency is explicit and xgettext can find the call sites.
"""

import gettext
import os

from stenmark import LOCALEDIR

GETTEXT_DOMAIN = "stenmark"

#: Languages Stenmark itself is translated into, as gettext codes. Kept as an
#: explicit list rather than discovered at runtime: GTK and libadwaita ship
#: catalogues for dozens of locales, so asking the system what exists would
#: offer languages in which only the odd stock button is actually translated.
#: This list says what *we* have. Adding a translation is two steps: add the
#: code to po/LINGUAS, and add it here with its name written in itself.
#:
#: "en" is the language of the source strings, so it needs no catalogue.
SUPPORTED_LANGUAGES = [
    ("en", "English"),
    ("de", "Deutsch"),
]

#: Settings key holding the override. Empty/absent means "follow the system".
LANGUAGE_KEY = "language"

#: Where to send someone who wants Stenmark in a language it does not speak
#: yet. TRANSLATING.md rather than the issue tracker: it documents the whole
#: workflow, and the point of the invitation is that adding a language is a
#: text file rather than a build environment.
TRANSLATE_URL = "https://github.com/mkay/stenmark/blob/main/TRANSLATING.md"


def _apply_language_override():
    """Point gettext at the configured language before any catalogue loads.

    Must happen before the translation object below is built, which is why it
    lives here rather than in __main__: this module is the one thing every
    caller of _() already imports, so the ordering cannot be got wrong by
    importing things in an unexpected order.

    LANGUAGE takes precedence over LC_ALL/LANG for gettext specifically, so
    the rest of the locale — number and date formatting, sorting — keeps
    following the system, which is what someone picking a UI language means.

    Read straight out of the settings file rather than through
    SettingsManager: that class pulls in GObject, and this runs during the
    import of the first module that wants a translated string.
    """
    try:
        import json
        from pathlib import Path

        with open(Path.home() / ".config" / "stenmark" / "settings.json") as f:
            choice = json.load(f).get(LANGUAGE_KEY, "")
    except Exception:  # noqa: BLE001 - a bad config must not stop startup
        return
    if choice and choice in {code for code, _label in SUPPORTED_LANGUAGES}:
        os.environ["LANGUAGE"] = choice


_apply_language_override()

_translation = gettext.translation(GETTEXT_DOMAIN, LOCALEDIR, fallback=True)

#: Translate a string. Falls back to the English source when no catalogue
#: exists for the current locale.
_ = _translation.gettext

#: Translate a counted string, picking the plural form for `n`.
ngettext = _translation.ngettext


def C_(context, message):
    """Translate `message` disambiguated by `context`.

    Use when the same English word needs different translations depending on
    where it appears — e.g. "Open" as a verb on a button versus a noun in a
    menu heading.
    """
    return _translation.pgettext(context, message)
