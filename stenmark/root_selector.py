"""Drill-down root-folder selector.

An alternative to the flat GtkDropDown in the sidebar header: a MenuButton
whose popover holds an AdwNavigationView, so each page lists one folder's
subfolders and pushes a new page when you descend. Two affordances per row:

    [icon] Name .............. [check] [>]

Clicking the row body picks that folder as the root and closes the popup;
clicking the trailing chevron descends into it. The folder a page *is*
(which has no row of its own on that page) is pickable from the check
button in the page's header bar, which is what makes the ceiling folder —
the one page with no parent — reachable.

Kept in its own module so window.py only has to choose between this and
the dropdown; see ROOT_DRILLDOWN there.
"""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GObject  # noqa: E402

from stenmark.i18n import _
from stenmark.sidebar import _collect_subdirs


# The popover is a fixed width: the pages inside it hold different names at
# different lengths, and letting each one size itself makes the popover jump
# on every push.
POPOVER_WIDTH = 280
# Past this the page scrolls instead of growing the popover downward.
PAGE_MAX_HEIGHT = 360


class RootSelector(Gtk.MenuButton):
    """Sidebar-header button that drills down through the folder tree."""

    __gsignals__ = {
        # Emitted with the absolute path the user picked.
        "folder-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(
            tooltip_text=_("Change root folder"),
            css_classes=["root-drilldown"],
            always_show_arrow=True,
        )

        self._ceiling = None
        self._current = None

        # Button face. A check rather than a folder — wearing the same icon
        # as the rows underneath is what made this read as one more folder to
        # open. Spacing and icon size are picked so the *label* lands on the
        # folder names' column below it — 1px to their left, since those are
        # bold and this isn't — with the check a touch smaller so it doesn't
        # outweigh a row's icon.
        face = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        icon = Gtk.Image(icon_name="stenmark-check-square-symbolic")
        icon.set_pixel_size(14)
        # 5 rather than 6: a 1px nudge left for the whole face, paying back
        # the optical weight the rows get from their bold labels.
        icon.set_margin_start(5)
        face.append(icon)
        self._label = Gtk.Label(xalign=0, hexpand=True, ellipsize=3)  # END
        face.append(self._label)
        self.set_child(face)

        self._nav = Adw.NavigationView(width_request=POPOVER_WIDTH)
        # Sizes are fixed above, so the view never has to negotiate one.
        self._nav.set_vexpand(False)

        popover = Gtk.Popover(child=self._nav, has_arrow=False)
        popover.add_css_class("menu")
        popover.connect("closed", self._on_closed)
        self.set_popover(popover)

    # ---- Public API (mirrors what window.py asks of the dropdown) --------

    def set_ceiling(self, path):
        """Point the selector at a folder tree and rebuild the first page."""
        self._ceiling = path
        self._nav.replace([self._make_page(path)])

    def set_current(self, path):
        """Mark `path` as the active root and relabel the button."""
        self._current = os.path.normpath(path) if path else None
        base = os.path.basename(path.rstrip(os.sep)) or path if path else ""
        self._label.set_label(base)
        self._refresh_marks()

    def refresh(self):
        """Re-read the visible pages from disk after folders changed.

        Only the pages still backed by a real folder survive; if a folder was
        deleted out from under us the stack is trimmed to its last valid page.
        """
        if self._ceiling is None:
            return
        pages = []
        for page in self._nav.get_navigation_stack():
            if not os.path.isdir(page.get_tag()):
                break
            pages.append(self._make_page(page.get_tag()))
        self._nav.replace(pages or [self._make_page(self._ceiling)])
        self._refresh_marks()

    # ---- Page construction ----------------------------------------------

    def _make_page(self, path):
        """Build one AdwNavigationPage listing `path`'s subfolders."""
        name = os.path.basename(path.rstrip(os.sep)) or path

        listbox = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            css_classes=["root-drilldown-list"],
        )
        listbox.connect("row-activated", self._on_row_activated)
        for index, (child_path, child_name) in enumerate(_collect_subdirs(path)):
            listbox.append(self._make_row(child_path, child_name, index))

        if listbox.get_first_child() is None:
            placeholder = Gtk.Label(
                label=_("No subfolders"),
                css_classes=["dim-label"],
                margin_top=12, margin_bottom=12,
            )
            listbox.set_placeholder(placeholder)

        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=PAGE_MAX_HEIGHT,
            child=listbox,
        )

        # Both sets off: an AdwHeaderBar inside a popover otherwise inherits
        # the *window's* close/minimise buttons and draws them on the page.
        header = Adw.HeaderBar(
            show_start_title_buttons=False,
            show_end_title_buttons=False,
        )
        # Picks the folder this page *is*. The only way to reach the ceiling,
        # which never appears as a row anywhere.
        use_btn = Gtk.Button(
            icon_name="object-select-symbolic",
            tooltip_text=_("Use this folder as root"),
            css_classes=["flat"],
        )
        use_btn.connect("clicked", lambda _b: self._choose(path))
        header.pack_end(use_btn)

        toolbar = Adw.ToolbarView(content=scroller)
        toolbar.add_top_bar(header)

        page = Adw.NavigationPage(child=toolbar, title=name)
        # The tag doubles as the page's identity for refresh() and for the
        # mark sweep below, so the widget tree never has to be walked to work
        # out which folder a page shows.
        page.set_tag(path)
        page._use_button = use_btn
        page._rows = listbox
        return page

    def _make_row(self, path, name, index):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.append(Gtk.Image(icon_name="stenmark-folder-bold-symbolic"))
        # ellipsize alone doesn't stop a long name from widening the popover:
        # a GtkLabel still reports the whole string as its natural width until
        # max-width-chars is set. Without this the popup resizes on every push.
        box.append(Gtk.Label(
            label=name, xalign=0, hexpand=True, ellipsize=3,
            max_width_chars=1,
        ))

        check = Gtk.Image(icon_name="object-select-symbolic", visible=False)
        box.append(check)

        # Only folders you can actually descend into get a chevron; a leaf
        # folder would otherwise offer a button that opens an empty page.
        if _collect_subdirs(path):
            chevron = Gtk.Button(
                icon_name="go-next-symbolic",
                tooltip_text=_("Show subfolders"),
                css_classes=["flat", "circular", "root-drilldown-descend"],
                valign=Gtk.Align.CENTER,
            )
            chevron.connect("clicked", lambda _b, p=path: self._descend(p))
            box.append(chevron)
        else:
            # Keeps the labels of leaf and branch rows on the same column.
            box.append(Gtk.Box(width_request=28))

        row = Gtk.ListBoxRow(child=box, activatable=True)
        row.add_css_class("root-drilldown-row")
        if index % 2 == 1:
            # On the box, not the row: a background set on a row from an app
            # provider is dropped silently — the same quirk the dropdown's
            # stripe already works around. The box is pulled back out over
            # the row's padding so the stripes meet and reach the edges.
            box.add_css_class("root-row-alt")
        row._path = path
        row._check = check
        return row

    # ---- Behaviour -------------------------------------------------------

    def _on_row_activated(self, _listbox, row):
        self._choose(row._path)

    def _descend(self, path):
        self._nav.push(self._make_page(path))
        self._refresh_marks()

    def _choose(self, path):
        self.get_popover().popdown()
        self.emit("folder-selected", path)

    def _refresh_marks(self):
        """Show the checkmark on whichever row/header matches the root."""
        for page in self._nav.get_navigation_stack():
            # Greyed rather than hidden: a button that vanishes on the page
            # you are already rooted at reads as a missing feature.
            page._use_button.set_sensitive(
                os.path.normpath(page.get_tag()) != self._current
            )
            row = page._rows.get_first_child()
            while row is not None:
                row._check.set_visible(
                    os.path.normpath(row._path) == self._current
                )
                row = row.get_next_sibling()

    def _on_closed(self, _popover):
        # Reopen where the user expects to start rather than wherever they
        # happened to drill to last time.
        if self._ceiling is not None:
            self._nav.replace([self._make_page(self._ceiling)])
            self._refresh_marks()
