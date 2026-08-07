import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib, GObject, Gdk

from stenmark.i18n import _, ngettext

from stenmark.document_panel import (
    _collect_md_files,
    _collect_md_files_recursive,
    _read_title,
)
from stenmark.sidebar import Sidebar


class SearchPanel(Gtk.Box):
    """Full-text search across all markdown documents."""

    __gsignals__ = {
        "file-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "close-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "tag-filter-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._settings = settings
        self._search_generation = 0
        self._debounce_id = None
        self._folder = Sidebar.ALL_DOCUMENTS  # search scope
        self._scope_name = "All Documents"

        # Search bar
        bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=8,
        )
        bar.add_css_class("toolbar")

        self._entry = Gtk.SearchEntry(
            placeholder_text=_("Search all documents\u2026"),
            hexpand=True,
        )
        self._entry.connect("search-changed", self._on_search_changed)
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key_pressed)
        self._entry.add_controller(key_ctl)
        bar.append(self._entry)

        self._count_label = Gtk.Label(
            css_classes=["dim-label", "caption"],
        )
        self._count_label.set_visible(False)
        bar.append(self._count_label)

        self.append(bar)

        # Results area
        self._scrolled = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp(maximum_size=640, tightening_threshold=400)

        self._results_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12,
            margin_end=12,
            margin_top=4,
            margin_bottom=12,
        )
        clamp.set_child(self._results_box)
        self._scrolled.set_child(clamp)
        self.append(self._scrolled)

        # Empty / status page
        self._status = Adw.StatusPage(
            icon_name="stenmark-search-symbolic",
            title=_("Search Documents"),
            description=_("Search for text across all your markdown files."),
            vexpand=True,
        )
        tag_link = Gtk.Button(
            label=_("or filter by tags"),
            css_classes=["flat", "link"],
            halign=Gtk.Align.CENTER,
        )
        tag_link.connect("clicked", lambda _b: self.emit("tag-filter-requested"))
        self._status.set_child(tag_link)
        self.append(self._status)

        # Spinner overlay
        self._spinner = Gtk.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self._spinner.set_visible(False)

        self._scrolled.set_visible(False)

    def set_folder(self, folder):
        """Set search scope: a directory path, ALL_DOCUMENTS, or NO_FOLDER."""
        self._folder = folder
        if folder == Sidebar.ALL_DOCUMENTS:
            self._scope_name = _("All Documents")
        elif folder == Sidebar.NO_FOLDER:
            self._scope_name = _("Files without Folder")
        else:
            self._scope_name = f"\u201c{os.path.basename(folder)}\u201d"
        self._entry.set_placeholder_text(
            _("Search in {scope}\u2026").format(scope=self._scope_name))
        self._status.set_title(_("Search {scope}").format(scope=self._scope_name))
        self._status.set_description(_("What are you looking for?"))

    def focus_search(self):
        self._entry.grab_focus()

    def clear(self):
        self._entry.set_text("")
        self._clear_results()
        self._scrolled.set_visible(False)
        self._status.set_visible(True)
        self._status.set_title(_("Search {scope}").format(scope=self._scope_name))
        self._status.set_description(
            _("Search for text in {scope}.").format(scope=self._scope_name))
        self._count_label.set_visible(False)

    def _clear_results(self):
        child = self._results_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._results_box.remove(child)
            child = nxt

    def _on_key_pressed(self, _ctl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.emit("close-requested")
            return True
        return False

    def _on_search_changed(self, entry):
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        query = entry.get_text().strip()
        if not query:
            self.clear()
            return
        self._debounce_id = GLib.timeout_add(300, self._start_search, query)

    def _start_search(self, query):
        self._debounce_id = None
        self._search_generation += 1
        gen = self._search_generation

        self._clear_results()
        self._status.set_visible(False)
        self._scrolled.set_visible(True)
        self._count_label.set_visible(False)

        root = self._settings.root_directory
        folder = self._folder

        if folder == Sidebar.ALL_DOCUMENTS:
            groups = _collect_md_files_recursive(root)
            all_files = []
            for files in groups.values():
                all_files.extend(files)
        elif folder == Sidebar.NO_FOLDER:
            all_files = _collect_md_files(root)
        else:
            groups = _collect_md_files_recursive(folder)
            all_files = []
            for files in groups.values():
                all_files.extend(files)

        self._do_search(all_files, query.lower(), gen, 0, 0)
        return GLib.SOURCE_REMOVE

    def _do_search(self, files, query, gen, index, match_count):
        """Process files in batches via idle_add to keep UI responsive."""
        if gen != self._search_generation:
            return
        batch = 20
        end = min(index + batch, len(files))
        root = self._settings.root_directory

        listbox = None

        for i in range(index, end):
            path = files[i]
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue

            lower_content = content.lower()
            pos = lower_content.find(query)
            if pos == -1:
                continue

            match_count += 1

            # Build snippet
            snippet = self._build_snippet(content, pos, len(query))

            # Build row
            if listbox is None:
                listbox = Gtk.ListBox(css_classes=["boxed-list"])
                listbox.set_selection_mode(Gtk.SelectionMode.NONE)
                listbox.connect("row-activated", self._on_row_activated)

            row = self._make_result_row(path, root, snippet)
            listbox.append(row)

        if listbox is not None:
            self._results_box.append(listbox)

        if end < len(files):
            GLib.idle_add(self._do_search, files, query, gen, end, match_count)
        else:
            # Search complete
            if match_count == 0:
                self._scrolled.set_visible(False)
                self._status.set_visible(True)
                self._status.set_title(_("No Results"))
                self._status.set_description(_("No documents match your search."))
                self._count_label.set_visible(False)
            else:
                self._count_label.set_label(
                    ngettext("{n} result", "{n} results", match_count)
                    .format(n=match_count)
                )
                self._count_label.set_visible(True)

    @staticmethod
    def _build_snippet(content, pos, query_len):
        """Extract a context snippet around the match position."""
        ctx = 60
        start = max(0, pos - ctx)
        end = min(len(content), pos + query_len + ctx)

        # Snap to word boundaries
        if start > 0:
            space = content.rfind(" ", start, pos)
            if space != -1:
                start = space + 1
        if end < len(content):
            space = content.find(" ", pos + query_len, end)
            if space != -1:
                end = space

        before = content[start:pos].replace("\n", " ")
        match = content[pos:pos + query_len].replace("\n", " ")
        after = content[pos + query_len:end].replace("\n", " ")

        prefix = "\u2026" if start > 0 else ""
        suffix = "\u2026" if end < len(content) else ""

        # Escape markup in all parts
        before = GLib.markup_escape_text(prefix + before)
        match = GLib.markup_escape_text(match)
        after = GLib.markup_escape_text(after + suffix)

        return f"{before}<b>{match}</b>{after}"

    def _make_result_row(self, path, root, snippet_markup):
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_start=12,
            margin_end=12,
            margin_top=10,
            margin_bottom=10,
        )

        icon = Gtk.Image(icon_name="stenmark-document-all-symbolic")
        icon.set_valign(Gtk.Align.START)

        info_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            hexpand=True,
            spacing=2,
        )

        basename = os.path.basename(path)
        stem = basename[:-3] if basename.lower().endswith(".md") else basename
        md_title = _read_title(path)
        display_name = md_title or stem

        title = Gtk.Label(
            label=display_name,
            css_classes=["heading"],
            xalign=0,
            ellipsize=3,  # PANGO_ELLIPSIZE_END
        )

        rel = os.path.relpath(path, root)
        subtitle = Gtk.Label(
            label=rel,
            css_classes=["dim-label", "caption"],
            xalign=0,
            ellipsize=3,
        )

        snippet_label = Gtk.Label(
            use_markup=True,
            css_classes=["caption"],
            xalign=0,
            wrap=True,
            wrap_mode=2,  # PANGO_WRAP_WORD_CHAR
        )
        snippet_label.set_markup(snippet_markup)

        info_box.append(title)
        info_box.append(subtitle)
        info_box.append(snippet_label)

        box.append(icon)
        box.append(info_box)

        row = Gtk.ListBoxRow(child=box)
        row._file_path = path
        return row

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, "_file_path"):
            self.emit("file-selected", row._file_path)
