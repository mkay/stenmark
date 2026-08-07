# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

"""The three ways to say Stenmark is worth keeping around.

Stenmark collects nothing, which also means it reports nothing back: there is no
download count, no telemetry, no way of telling whether a release landed. This
dialog is the substitute — an explicit ask, offered once from the main menu and
never nagged, with the free options first so the money one reads as the
afterthought it is.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from stenmark.i18n import _

#: Where the source lives. A star is the one number this project actually gets
#: to see, so it is worth asking for by name.
REPO_URL = "https://github.com/mkay/stenmark"

KOFI_URL = "https://ko-fi.com/s1ngular"

#: A page carrying a like button the visitor presses. The count deliberately
#: does not come from the visit itself: a privacy-minded browser suppresses a
#: plain hit counter, which would quietly under-count exactly the audience this
#: app has. A button press is an explicit act nothing has reason to withhold,
#: and it is the honest thing to ask for — nothing is recorded unless the
#: visitor means it. The query string names the app, so one page serves all.
LIKE_URL = "https://singular.de/apps/feedback/?stenmark"


class SupportDialog(Adw.AlertDialog):
    """Intro, three ways, and a Close button."""

    def __init__(self, parent=None):
        super().__init__(
            # Translators: title of the "Support Stenmark" dialog.
            heading=_("Keep this app alive"),
        )
        # Kept rather than taken from get_root() at click time: an Adw.Dialog
        # sits inside its host window, and the launcher wants the window.
        self._parent = parent

        self.add_response("close", _("Close"))
        self.set_default_response("close")
        self.set_close_response("close")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)

        for text in (
            _("This app doesn't track. Anything.\n"
              "The downside is I have no idea if or how often it's used or "
              "downloaded. Could be zero, could be a secret cult following. I "
              "genuinely don't know."),
            _("Am I wasting my time publishing it? You tell me."),
            _("There are three (maybe more) ways to keep me motivated:"),
        ):
            box.append(Gtk.Label(
                label=text, wrap=True, xalign=0.0, halign=Gtk.Align.START,
            ))

        box.append(self._way(
            title=_("The easy way"),
            action=_("Give it a like"),
            icon="emote-love-symbolic",
            note=_("Opens a page on my website with a like button. Nothing is "
                   "counted until you press it — just the press and an "
                   "anonymised IP."),
            url=LIKE_URL,
            # The one that costs nothing, so it gets the accented button.
            emphasised=True,
        ))
        box.append(self._way(
            title=_("The nerdy way"),
            action=_("Star it on GitHub"),
            icon="starred-symbolic",
            note=_("A star is a number I can actually see, and it helps others "
                   "find it."),
            url=REPO_URL,
        ))
        box.append(self._way(
            title=_("The generous way"),
            action=_("Support it on Ko-fi"),
            icon="emblem-favorite-symbolic",
            note=_("Entirely optional. Stenmark is and stays free either way."),
            url=KOFI_URL,
        ))

        # A cap rather than a request: a GtkScrolledWindow still shrinks below
        # it when the window is short, so the ceiling only costs space where
        # there is space. Sized for the longest translation rather than the
        # English — German runs ~70px taller at this width, and a cap that fits
        # only the source language quietly scrolls the last button out of sight.
        scroller = Gtk.ScrolledWindow(
            propagate_natural_height=True,
            max_content_height=640,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            child=box,
        )
        # AlertDialog sizes itself to its heading, which would leave the prose
        # wrapping every few words.
        scroller.set_size_request(420, -1)
        self.set_extra_child(scroller)

    def _way(self, title, action, icon, note, url, emphasised=False):
        """One block: a heading, the button that does the thing, small print."""
        content = Adw.ButtonContent(icon_name=icon, label=action)
        button = Gtk.Button(child=content, halign=Gtk.Align.START)
        if emphasised:
            button.add_css_class("suggested-action")
        button.connect("clicked", self._on_open, url)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        heading = Gtk.Label(label=title, xalign=0.0, halign=Gtk.Align.START)
        heading.add_css_class("heading")
        col.append(heading)
        col.append(button)
        small = Gtk.Label(
            label=note, wrap=True, xalign=0.0, halign=Gtk.Align.START,
        )
        small.add_css_class("caption")
        small.add_css_class("dim-label")
        col.append(small)
        return col

    def _on_open(self, _button, url):
        # The dialog stays up: someone who stars the repo may well want the
        # Ko-fi link too, and dismissing it would make them go find it again.
        Gtk.UriLauncher(uri=url).launch(self._parent, None, None, None)


def present(parent):
    SupportDialog(parent).present(parent)
