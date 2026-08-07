# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Release notes shown once after an update, and again on demand from About.

The notes themselves live in data/whatsnew.md and are bundled into the GResource,
so they travel with the build and cannot go missing from an install. They are
deliberately not translated: unlike every other string in the app they never pass
through gettext, and stay English whatever the language setting says.
"""

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from stenmark import APP_NAME, VERSION
from stenmark.i18n import _

RESOURCE_PATH = "/de/singular/stenmark/whatsnew.md"

# Remembers the version whose notes have been shown. Compared against VERSION, so
# it only ever moves forward — a downgrade re-shows the older version's notes,
# which is the honest thing to do since they describe what is actually running.
SEEN_KEY = "whats_new_seen"

#: Markdown links, `[label](url)`. Preferred over a bare URL: a full URL set in
#: a narrow dialog wraps mid-scheme and reads like debris.
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

#: Bare http(s) URLs, linkified as a fallback so a plainly-written URL still
#: works. Trailing punctuation is left out of the match so a link ending a
#: sentence does not swallow the full stop.
_URL_RE = re.compile(r"(https?://[^\s<>]*[^\s<>.,;:!?)\]])")


def load_notes():
    """The bullets from data/whatsnew.md, or an empty list if unreadable.

    Never raises: release notes are a nicety, and a malformed file must not be
    able to stop the app from starting.
    """
    try:
        data = Gio.resources_lookup_data(RESOURCE_PATH, Gio.ResourceLookupFlags.NONE)
        text = data.get_data().decode("utf-8")
    except (GLib.Error, UnicodeDecodeError):
        return []

    # Drop the authoring comment, then treat every remaining non-blank line as one
    # bullet with an optional marker.
    while "<!--" in text and "-->" in text:
        head, _sep, rest = text.partition("<!--")
        text = head + rest.partition("-->")[2]

    bullets = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0] in "-*•":
            line = line[1:].strip()
        if line:
            bullets.append(line)
    return bullets


def _linkify(bullet):
    """Escape a bullet for Pango and turn any bare URL into a link.

    Keeps whatsnew.md plain text: a URL is written as itself, with no markup to
    author or to escape by hand. GTK's default ::activate-link handler opens it,
    so nothing needs wiring up at the label.
    """
    def bare(text):
        # re.split with one capture group alternates text, match, text, …
        parts = _URL_RE.split(text)
        return "".join(
            f'<a href="{e}">{e}</a>' if i % 2 else e
            for i, e in ((i, GLib.markup_escape_text(p)) for i, p in enumerate(parts))
        )

    out = []
    last = 0
    for m in _MD_LINK_RE.finditer(bullet):
        out.append(bare(bullet[last:m.start()]))
        label = GLib.markup_escape_text(m.group(1))
        url = GLib.markup_escape_text(m.group(2))
        out.append(f'<a href="{url}">{label}</a>')
        last = m.end()
    out.append(bare(bullet[last:]))
    return "".join(out)


def _unlink(bullet):
    """Escape a bullet, reducing markdown links to their label.

    Adw.AboutDialog's release-notes parser takes the AppStream subset, which has
    no <a>: handing it one makes it reject the whole document.
    """
    return GLib.markup_escape_text(_MD_LINK_RE.sub(r"\1", bullet))


def release_notes_markup():
    """The notes as the AppStream-flavoured HTML subset Adw.AboutDialog wants."""
    bullets = load_notes()
    if not bullets:
        return ""
    items = "".join(f"<li>{_unlink(b)}</li>" for b in bullets)
    return f"<ul>{items}</ul>"


class WhatsNewDialog(Adw.AlertDialog):
    """The bullets in a plain dismissable dialog."""

    def __init__(self, bullets):
        super().__init__(
            # Translators: dialog title for the release notes shown after an
            # update. The notes themselves are always English.
            heading=_("What's New"),
            body=f"{APP_NAME} {VERSION}",
        )
        self.add_response("close", _("Close"))
        self.set_default_response("close")
        self.set_close_response("close")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for bullet in bullets:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.append(Gtk.Label(label="•", valign=Gtk.Align.START))
            label = Gtk.Label(
                label=_linkify(bullet),
                use_markup=True,
                wrap=True,
                xalign=0.0,
                halign=Gtk.Align.START,
                hexpand=True,
            )
            row.append(label)
            box.append(row)

        # Long notes scroll rather than growing the dialog past the screen. The
        # height is a cap, not a request: four or five bullets never reach it.
        scroller = Gtk.ScrolledWindow(
            propagate_natural_height=True,
            max_content_height=440,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            child=box,
        )
        # AlertDialog sizes itself to its heading and body, which leaves the
        # bullets wrapping every few words. Ask for something readable instead.
        scroller.set_size_request(380, -1)
        self.set_extra_child(scroller)


def present(parent):
    """Show the notes unconditionally. Used by the About dialog's entry point."""
    bullets = load_notes()
    if not bullets:
        return
    WhatsNewDialog(bullets).present(parent)


def present_if_updated(parent, settings, is_first_run):
    """Show the notes if this is the first launch on a new version.

    [is_first_run] must be sampled before any setting is written this session —
    see SettingsManager.first_run. A fresh install has nothing "new" to report,
    and greeting a first-time user with release notes is just confusing.
    """
    seen = settings.get(SEEN_KEY)
    if seen == VERSION:
        return GLib.SOURCE_REMOVE

    # Recorded now rather than on dismissal: if the app dies while the dialog is
    # up the notes have still been seen, and re-showing them every launch would
    # be worse than missing them once.
    settings.set(SEEN_KEY, VERSION)

    # No record at all means either a fresh install or an upgrade from a version
    # that predates this feature. Only the latter gets the notes.
    if not seen and is_first_run:
        return GLib.SOURCE_REMOVE

    present(parent)
    return GLib.SOURCE_REMOVE
