# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GObject, Gdk

from stenmark.i18n import _, ngettext

from stenmark.document_panel import _read_title


class TagPanel(Gtk.Box):
    """Tag-based document filter pane."""

    __gsignals__ = {
        "file-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "close-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings, tag_index):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._settings = settings
        self._tag_index = tag_index
        self._selected_tags = set()

        # ---- Tag selector area ----
        tag_bar = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=4,
        )

        # Filter entry for tags
        self._entry = Gtk.SearchEntry(
            placeholder_text=_("Filter tags\u2026"),
            hexpand=True,
        )
        self._entry.connect("search-changed", self._on_entry_changed)
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_key_pressed)
        self._entry.add_controller(key_ctl)
        tag_bar.append(self._entry)

        # Scrollable tag chip area
        tag_scroll = Gtk.ScrolledWindow(
            vexpand=True,
        )
        tag_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._tags_flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=20,
            homogeneous=False,
            margin_top=4,
            margin_bottom=4,
            valign=Gtk.Align.START,
        )
        self._tags_flow.set_row_spacing(4)
        self._tags_flow.set_column_spacing(4)
        tag_scroll.set_child(self._tags_flow)
        tag_bar.append(tag_scroll)

        # Selected tags + count
        self._info_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_top=2,
        )
        self._count_label = Gtk.Label(
            css_classes=["dim-label", "caption"],
        )
        self._count_label.set_visible(False)
        self._info_box.append(self._count_label)

        spacer = Gtk.Box(hexpand=True)
        self._info_box.append(spacer)

        self._clear_btn = Gtk.Button(
            label=_("Clear"),
            css_classes=["flat", "caption"],
            visible=False,
        )
        self._clear_btn.connect("clicked", self._on_clear_clicked)
        self._info_box.append(self._clear_btn)

        tag_bar.append(self._info_box)

        # ---- Resizable split: tags on top, results below ----
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self._paned.set_shrink_start_child(False)
        self._paned.set_shrink_end_child(False)
        self._paned.set_resize_start_child(False)
        self._paned.set_resize_end_child(True)
        self._paned.set_start_child(tag_bar)

        # ---- Results area ----
        self._bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)

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
        self._bottom_box.append(self._scrolled)

        # Empty state
        self._status = Adw.StatusPage(
            icon_name="stenmark-tag-symbolic",
            title=_("Filter by Tag"),
            description=_("Select tags above to find matching documents."),
            vexpand=True,
        )
        self._bottom_box.append(self._status)

        self._scrolled.set_visible(False)

        self._paned.set_end_child(self._bottom_box)
        self._paned.set_position(240)
        self.append(self._paned)

    def focus_entry(self):
        self._entry.grab_focus()

    def select_tag(self, tag):
        """Pre-select a single tag and show results."""
        self._selected_tags = {tag}
        self._entry.set_text("")
        self._rebuild_tag_chips()
        self._update_results()

    def show_tags(self):
        """Rebuild the tag chip list from the index."""
        self._rebuild_tag_chips()
        if not self._selected_tags:
            self._scrolled.set_visible(False)
            self._status.set_visible(True)
        else:
            self._update_results()

    def clear(self):
        self._entry.set_text("")
        self._selected_tags.clear()
        self._clear_results()
        self._scrolled.set_visible(False)
        self._status.set_visible(True)
        self._status.set_title(_("Filter by Tag"))
        self._status.set_description(_("Select tags above to find matching documents."))
        self._count_label.set_visible(False)
        self._clear_btn.set_visible(False)
        self._rebuild_tag_chips()

    # ---- Tag chips ----

    def _rebuild_tag_chips(self):
        while True:
            child = self._tags_flow.get_first_child()
            if child is None:
                break
            self._tags_flow.remove(child)

        filter_text = self._entry.get_text().strip().lower()
        all_tags = self._tag_index.all_tags()

        if not all_tags:
            label = Gtk.Label(
                label=_("No tags found"),
                css_classes=["dim-label"],
            )
            self._tags_flow.append(label)
            return

        for tag in all_tags:
            if filter_text and filter_text not in tag:
                continue
            count = self._tag_index.tag_count(tag)
            active = tag in self._selected_tags
            btn = Gtk.ToggleButton(
                active=active,
                css_classes=["tag-filter-chip"],
            )
            btn_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=4,
            )
            btn_box.append(Gtk.Label(label=tag))
            cnt_lbl = Gtk.Label(
                label=str(count),
                css_classes=["dim-label", "caption"],
            )
            btn_box.append(cnt_lbl)
            btn.set_child(btn_box)
            btn.connect("toggled", self._on_tag_toggled, tag)
            self._tags_flow.append(btn)

    def _on_tag_toggled(self, btn, tag):
        if btn.get_active():
            self._selected_tags.add(tag)
        else:
            self._selected_tags.discard(tag)
        self._update_results()

    def _on_entry_changed(self, _entry):
        self._rebuild_tag_chips()

    def _on_key_pressed(self, _ctl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            if self._entry.get_text():
                self._entry.set_text("")
                return True
            self.emit("close-requested")
            return True
        return False

    def _on_clear_clicked(self, _btn):
        self._selected_tags.clear()
        self._rebuild_tag_chips()
        self._clear_results()
        self._scrolled.set_visible(False)
        self._status.set_visible(True)
        self._count_label.set_visible(False)
        self._clear_btn.set_visible(False)

    # ---- Results ----

    def _clear_results(self):
        child = self._results_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._results_box.remove(child)
            child = nxt

    def _update_results(self):
        self._clear_results()

        if not self._selected_tags:
            self._scrolled.set_visible(False)
            self._status.set_visible(True)
            self._count_label.set_visible(False)
            self._clear_btn.set_visible(False)
            return

        self._clear_btn.set_visible(True)

        # Collect files matching ALL selected tags (intersection)
        sets = [set(self._tag_index.get_files(tag)) for tag in self._selected_tags]
        matched = sets[0].intersection(*sets[1:]) if sets else set()

        if not matched:
            self._scrolled.set_visible(False)
            self._status.set_visible(True)
            self._status.set_title(_("No Results"))
            self._status.set_description(_("No documents match the selected tags."))
            self._count_label.set_visible(False)
            return

        self._status.set_visible(False)
        self._scrolled.set_visible(True)

        # Group by directory
        root = self._settings.root_directory
        groups = {}
        for f in sorted(matched):
            d = os.path.dirname(f)
            groups.setdefault(d, []).append(f)

        match_count = len(matched)
        self._count_label.set_label(
            ngettext("{n} document", "{n} documents", match_count)
            .format(n=match_count)
        )
        self._count_label.set_visible(True)

        for dir_path in sorted(groups.keys()):
            if dir_path == root:
                section_name = _("No Folder")
            else:
                section_name = os.path.relpath(dir_path, root)

            header = Gtk.Label(
                label=section_name,
                xalign=0,
                css_classes=["heading"],
                margin_top=12,
                margin_bottom=4,
                margin_start=4,
            )
            self._results_box.append(header)

            listbox = Gtk.ListBox(css_classes=["boxed-list"])
            listbox.set_selection_mode(Gtk.SelectionMode.NONE)
            listbox.connect("row-activated", self._on_row_activated)

            for path in sorted(groups[dir_path], key=lambda p: os.path.basename(p).lower()):
                row = self._make_result_row(path, root)
                listbox.append(row)
            self._results_box.append(listbox)

    def _make_result_row(self, path, root):
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_start=12,
            margin_end=12,
            margin_top=10,
            margin_bottom=10,
        )

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
            ellipsize=3,
        )

        rel = os.path.relpath(path, root)
        subtitle = Gtk.Label(
            label=rel,
            css_classes=["dim-label", "caption"],
            xalign=0,
            ellipsize=3,
        )

        info_box.append(title)
        info_box.append(subtitle)

        # Show file's tags as chips
        file_tags = self._tag_index.get_tags(path)
        if file_tags:
            tags_box = Gtk.FlowBox(
                selection_mode=Gtk.SelectionMode.NONE,
                max_children_per_line=10,
                homogeneous=False,
            )
            tags_box.set_row_spacing(2)
            tags_box.set_column_spacing(4)
            for tag in file_tags:
                chip = Gtk.Label(label=tag, css_classes=["caption", "tag-chip"])
                tags_box.append(chip)
            info_box.append(tags_box)

        box.append(info_box)

        row = Gtk.ListBoxRow(child=box)
        row._file_path = path
        return row

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, "_file_path"):
            self.emit("file-selected", row._file_path)
