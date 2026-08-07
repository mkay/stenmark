# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import os
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gio, GObject, Gdk, Graphene

from stenmark.i18n import _, ngettext

from stenmark.sidebar import Sidebar, _count_md_files


def _collect_subdirs(root):
    """Return sorted list of (path, name) for immediate subdirectories."""
    dirs = []
    try:
        for entry in sorted(os.scandir(root), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                dirs.append((entry.path, entry.name))
    except OSError:
        pass
    return dirs


def _collect_md_files(dir_path):
    """Return sorted list of .md file paths in a directory (non-recursive)."""
    files = []
    try:
        for entry in sorted(os.scandir(dir_path), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_file() and entry.name.lower().endswith(".md"):
                files.append(entry.path)
    except OSError:
        pass
    return files


def _collect_md_files_recursive(root):
    """Return dict of {dir_path: [file_paths]} for all subdirs with .md files."""
    groups = {}
    # Root-level files
    root_files = _collect_md_files(root)
    if root_files:
        groups[root] = root_files
    try:
        for entry in sorted(os.scandir(root), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                _collect_subdir_files(entry.path, groups)
    except OSError:
        pass
    return groups


def _collect_subdir_files(dir_path, groups):
    """Recursively collect .md files into groups dict."""
    files = _collect_md_files(dir_path)
    if files:
        groups[dir_path] = files
    try:
        for entry in sorted(os.scandir(dir_path), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                _collect_subdir_files(entry.path, groups)
    except OSError:
        pass


def _read_title(path):
    """Return the first # heading from a markdown file, or None.

    Skips YAML frontmatter if present.
    """
    from stenmark.frontmatter import parse_frontmatter
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(4096)
    except OSError:
        return None
    _meta, body = parse_frontmatter(text)
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip() or None
        if line:
            return None
    return None


def _format_size(size):
    # Translators: {n} is a file size. B / KB / MB are the unit symbols.
    if size < 1024:
        return _("{n} B").format(n=size)
    elif size < 1024 * 1024:
        return _("{n} KB").format(n=f"{size / 1024:.1f}")
    else:
        return _("{n} MB").format(n=f"{size / (1024 * 1024):.1f}")


def _format_date(mtime):
    now = time.time()
    delta = now - mtime
    if delta < 60:
        return _("just now")
    elif delta < 3600:
        m = int(delta / 60)
        return ngettext("{n} min ago", "{n} min ago", m).format(n=m)
    elif delta < 86400:
        h = int(delta / 3600)
        return ngettext("{n}h ago", "{n}h ago", h).format(n=h)
    else:
        # Translators: strftime format for a file date, e.g. "Mar 04, 2025".
        return time.strftime(_("%b %d, %Y"), time.localtime(mtime))


class DocumentPanel(Gtk.Box):
    __gsignals__ = {
        "file-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "file-trashed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "file-renamed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "folder-navigated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "tag-clicked": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, settings, tag_index=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._settings = settings
        self._tag_index = tag_index
        self._current_folder = None
        self._browsing_folder = None  # actual dir being displayed (may differ from _current_folder when drilled in)
        self._context_path = None
        self._context_folder_path = None

        # Filter bar
        self._filter_bar = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=4,
        )
        self._filter_entry = Gtk.SearchEntry(
            placeholder_text=_("Filter documents\u2026"),
            hexpand=True,
        )
        self._filter_entry.connect("search-changed", self._on_filter_changed)
        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_filter_key_pressed)
        self._filter_entry.add_controller(key_ctl)
        self._filter_bar.append(self._filter_entry)
        self._filter_bar.set_visible(False)
        self._filter_text = ""
        self.append(self._filter_bar)

        # Main scrolled area
        self._scrolled = Gtk.ScrolledWindow(vexpand=True)

        self._clamp = Adw.Clamp(
            maximum_size=640,
            tightening_threshold=400,
        )

        self._content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12,
            margin_end=12,
            margin_top=12,
            margin_bottom=12,
        )

        self._clamp.set_child(self._content_box)
        self._scrolled.set_child(self._clamp)

        # Empty state
        self._empty = Adw.StatusPage(
            title=_("No Documents"),
            description=_("This folder has no markdown files."),
            icon_name="stenmark-search-symbolic",
            vexpand=True,
        )
        self._empty.set_visible(False)

        self.append(self._scrolled)
        self.append(self._empty)

        self._setup_context_menu()
        self._setup_pane_context_menu()

    def show_folder(self, folder_path):
        """Display documents for the given folder path, tag:name, or all if ALL_DOCUMENTS."""
        self._current_folder = folder_path
        self._clear()

        if folder_path.startswith("tag:"):
            self._browsing_folder = None
            self._show_tagged_documents(folder_path[4:])
        elif folder_path == Sidebar.ALL_DOCUMENTS:
            self._browsing_folder = None
            self._show_all_documents()
        elif folder_path == Sidebar.NO_FOLDER:
            self._browsing_folder = self._settings.root_directory
            self._show_single_folder(self._settings.root_directory, show_subdirs=False)
        else:
            self._browsing_folder = folder_path
            self._show_single_folder(folder_path)

    def _navigate_to(self, dir_path):
        """Drill into a subfolder within the document panel."""
        self._browsing_folder = dir_path
        self._clear()
        self._show_single_folder(dir_path)
        self.emit("folder-navigated", dir_path)

    def _clear(self):
        child = self._content_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._content_box.remove(child)
            child = next_child

    def _partition_pinned(self, files):
        """Split files into (pinned, unpinned) preserving order within each."""
        pinned, unpinned = [], []
        for f in files:
            if self._settings.is_pinned(f):
                pinned.append(f)
            else:
                unpinned.append(f)
        return pinned, unpinned

    def _show_single_folder(self, dir_path, show_subdirs=True):
        subdirs = _collect_subdirs(dir_path) if show_subdirs else []
        files = _collect_md_files(dir_path)

        if not files and not subdirs:
            self._scrolled.set_visible(False)
            self._empty.set_visible(True)
            return
        self._scrolled.set_visible(True)
        self._empty.set_visible(False)

        # Subfolder rows — pinned folders first
        if subdirs:
            folder_listbox = self._make_listbox()
            pinned_subdirs = [(p, n) for p, n in subdirs if self._settings.is_folder_pinned(p)]
            unpinned_subdirs = [(p, n) for p, n in subdirs if not self._settings.is_folder_pinned(p)]
            for spath, sname in pinned_subdirs + unpinned_subdirs:
                pinned = self._settings.is_folder_pinned(spath)
                folder_listbox.append(self._make_folder_row(spath, sname, pinned=pinned))
            self._content_box.append(folder_listbox)

        # Document rows
        if files:
            if subdirs:
                header = Gtk.Label(
                    label=_("Documents"),
                    xalign=0,
                    css_classes=["heading"],
                    margin_top=20,
                    margin_bottom=6,
                    margin_start=4,
                )
                self._content_box.append(header)

            pinned, unpinned = self._partition_pinned(files)
            listbox = self._make_listbox()
            for path in pinned + unpinned:
                listbox.append(self._make_document_row(path))
            self._content_box.append(listbox)
        self._apply_filter()

    def _make_folder_row(self, dir_path, name, pinned=False):
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_start=12,
            margin_end=12,
            margin_top=10,
            margin_bottom=10,
        )

        icon_name = "stenmark-pin-symbolic" if pinned else "stenmark-folder-symbolic"
        icon = Gtk.Image(icon_name=icon_name)
        icon.set_valign(Gtk.Align.START)

        info_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            hexpand=True,
            spacing=2,
        )

        title = Gtk.Label(
            label=name,
            css_classes=["heading"],
            xalign=0,
        )

        doc_count = _count_md_files(dir_path)
        subdir_count = len(_collect_subdirs(dir_path))
        parts = []
        if doc_count:
            parts.append(ngettext("{n} document", "{n} documents", doc_count)
                         .format(n=doc_count))
        if subdir_count:
            parts.append(ngettext("{n} folder", "{n} folders", subdir_count)
                         .format(n=subdir_count))
        if not parts:
            parts.append(_("Empty"))
        try:
            mtime = os.stat(dir_path).st_mtime
            parts.append(_format_date(mtime))
        except OSError:
            pass

        subtitle = Gtk.Label(
            label=" \u00b7 ".join(parts),
            css_classes=["dim-label", "caption"],
            xalign=0,
        )

        info_box.append(title)
        info_box.append(subtitle)
        box.append(icon)
        box.append(info_box)

        row = Gtk.ListBoxRow(child=box)
        row._folder_path = dir_path
        row._display_name = name.lower()

        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_folder_row_right_click, row)
        row.add_controller(gesture)

        return row

    def _show_tagged_documents(self, tag):
        """Show files that have the given tag, grouped by folder."""
        if not self._tag_index:
            return
        files = self._tag_index.get_files(tag)
        if not files:
            self._scrolled.set_visible(False)
            self._empty.set_visible(True)
            return
        self._scrolled.set_visible(True)
        self._empty.set_visible(False)

        root = self._settings.root_directory
        groups = {}
        for f in files:
            d = os.path.dirname(f)
            groups.setdefault(d, []).append(f)

        for dir_path in sorted(groups.keys()):
            if dir_path == root:
                section_name = "No Folder"
            else:
                section_name = os.path.relpath(dir_path, root)

            header = Gtk.Label(
                label=section_name,
                xalign=0,
                css_classes=["heading"],
                margin_top=20,
                margin_bottom=6,
                margin_start=4,
            )
            self._content_box.append(header)

            listbox = self._make_listbox()
            for path in sorted(groups[dir_path], key=lambda p: os.path.basename(p).lower()):
                listbox.append(self._make_document_row(path))
            self._content_box.append(listbox)
        self._apply_filter()

    def _show_all_documents(self):
        root = self._settings.root_directory
        groups = _collect_md_files_recursive(root)

        if not groups:
            self._scrolled.set_visible(False)
            self._empty.set_visible(True)
            return
        self._scrolled.set_visible(True)
        self._empty.set_visible(False)

        for dir_path, files in groups.items():
            # Section header
            if dir_path == root:
                section_name = "No Folder"
            else:
                section_name = os.path.relpath(dir_path, root)

            header = Gtk.Label(
                label=section_name,
                xalign=0,
                css_classes=["heading"],
                margin_top=20,
                margin_bottom=6,
                margin_start=4,
            )
            self._content_box.append(header)

            pinned, unpinned = self._partition_pinned(files)
            listbox = self._make_listbox()
            for path in pinned + unpinned:
                listbox.append(self._make_document_row(path))
            self._content_box.append(listbox)
        self._apply_filter()

    def _make_listbox(self):
        listbox = Gtk.ListBox(css_classes=["boxed-list"])
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.connect("row-activated", self._on_row_activated)
        return listbox

    def _make_document_row(self, path):
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
        )

        # Subtitle: filename + size + modified date
        try:
            stat = os.stat(path)
            size_date = f"{_format_size(stat.st_size)} \u00b7 {_format_date(stat.st_mtime)}"
        except OSError:
            size_date = ""

        if md_title:
            subtitle_text = f"{basename} \u00b7 {size_date}" if size_date else basename
        else:
            subtitle_text = size_date

        subtitle = Gtk.Label(
            label=subtitle_text,
            css_classes=["dim-label", "caption"],
            xalign=0,
        )

        info_box.append(title)
        info_box.append(subtitle)

        tags = self._tag_index.get_tags(path) if self._tag_index else []
        if tags:
            tags_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=6,
                margin_top=2,
            )
            for tag in tags:
                chip = Gtk.Label(
                    label=tag,
                    css_classes=["caption", "tag-chip-link"],
                )
                click = Gtk.GestureClick()
                click.connect("pressed", self._on_tag_label_pressed, tag)
                chip.add_controller(click)
                tags_box.append(chip)
            info_box.append(tags_box)

        box.append(info_box)

        if self._settings.is_pinned(path):
            pin_btn = Gtk.Button()
            pin_btn.add_css_class("flat")
            pin_btn.add_css_class("circular")
            pin_btn.set_valign(Gtk.Align.CENTER)
            pin_btn.set_tooltip_text("Remove pin")
            pin_icon = Gtk.Image.new_from_icon_name("stenmark-pin-symbolic")
            pin_icon.add_css_class("dim-label")
            pin_btn.set_child(pin_icon)
            pin_btn.connect("clicked", self._on_pin_icon_clicked, path)
            box.append(pin_btn)

        row = Gtk.ListBoxRow(child=box)
        row._file_path = path
        row._display_name = display_name.lower()
        row._tags = tags

        # Right-click gesture per row
        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_row_right_click, row)
        row.add_controller(gesture)

        return row

    # ---- Quick filter ---------------------------------------------------

    def toggle_filter(self):
        if self._filter_bar.get_visible():
            self.hide_filter()
        else:
            self._filter_bar.set_visible(True)
            self._filter_entry.grab_focus()

    def hide_filter(self):
        self._filter_bar.set_visible(False)
        self._filter_entry.set_text("")
        self._filter_text = ""
        self._apply_filter()

    def _on_filter_changed(self, entry):
        self._filter_text = entry.get_text().strip().lower()
        self._apply_filter()

    def _on_filter_key_pressed(self, _ctl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.hide_filter()
            return True
        return False

    def _apply_filter(self):
        """Show/hide rows based on current filter text."""
        query = self._filter_text
        if not query:
            # Show everything
            child = self._content_box.get_first_child()
            while child:
                child.set_visible(True)
                if isinstance(child, Gtk.ListBox):
                    row = child.get_first_child()
                    while row:
                        row.set_visible(True)
                        row = row.get_next_sibling()
                child = child.get_next_sibling()
            return

        child = self._content_box.get_first_child()
        while child:
            if isinstance(child, Gtk.ListBox):
                any_visible = False
                row = child.get_first_child()
                while row:
                    name = getattr(row, "_display_name", "")
                    basename = ""
                    if hasattr(row, "_file_path"):
                        basename = os.path.basename(row._file_path).lower()
                    elif hasattr(row, "_folder_path"):
                        basename = os.path.basename(row._folder_path).lower()
                    tag_match = any(query in t for t in getattr(row, "_tags", []))
                    visible = query in name or query in basename or tag_match
                    row.set_visible(visible)
                    if visible:
                        any_visible = True
                    row = row.get_next_sibling()
                child.set_visible(any_visible)
                # Also hide the preceding header label if all rows are hidden
                prev = child.get_prev_sibling()
                if prev and isinstance(prev, Gtk.Label):
                    prev.set_visible(any_visible)
            child = child.get_next_sibling()

    def _on_tag_label_pressed(self, gesture, _n_press, _x, _y, tag):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.emit("tag-clicked", tag)

    # ---- Row activation -------------------------------------------------

    def _on_row_activated(self, _listbox, row):
        if hasattr(row, "_folder_path"):
            self._navigate_to(row._folder_path)
        elif hasattr(row, "_file_path"):
            self.emit("file-selected", row._file_path)

    # ---- Context menu ---------------------------------------------------

    def _build_context_menu(self, path):
        pin_section = Gio.Menu()
        label = "Unpin" if self._settings.is_pinned(path) else "Pin"
        pin_section.append(label, "docpanel.toggle-pin")

        section = Gio.Menu()
        section.append(_("Open With…"), "docpanel.open-with")
        section.append(_("Rename"), "docpanel.rename")
        section.append(_("Move to Folder…"), "docpanel.move-to-folder")
        section.append(_("Move to Trash"), "docpanel.trash")
        section.append(_("Reveal in File Manager"), "docpanel.reveal")

        path_section = Gio.Menu()
        path_section.append(_("Copy Path"), "docpanel.copy-path")

        menu = Gio.Menu()
        menu.append_section(None, pin_section)
        menu.append_section(None, section)
        menu.append_section(None, path_section)
        return menu

    def _setup_context_menu(self):
        self._popover = Gtk.PopoverMenu()
        self._popover.set_parent(self)
        self._popover.set_has_arrow(False)
        self._context_rect = Gdk.Rectangle()

        group = Gio.SimpleActionGroup()

        open_with_action = Gio.SimpleAction.new("open-with", None)
        open_with_action.connect("activate", self._on_open_with_activate)
        group.add_action(open_with_action)

        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self._on_rename_activate)
        group.add_action(rename_action)

        move_action = Gio.SimpleAction.new("move-to-folder", None)
        move_action.connect("activate", self._on_move_to_folder_activate)
        group.add_action(move_action)

        trash_action = Gio.SimpleAction.new("trash", None)
        trash_action.connect("activate", self._on_trash_activate)
        group.add_action(trash_action)

        reveal_action = Gio.SimpleAction.new("reveal", None)
        reveal_action.connect("activate", self._on_reveal_activate)
        group.add_action(reveal_action)

        copy_path_action = Gio.SimpleAction.new("copy-path", None)
        copy_path_action.connect("activate", self._on_copy_path_activate)
        group.add_action(copy_path_action)

        toggle_pin_action = Gio.SimpleAction.new("toggle-pin", None)
        toggle_pin_action.connect("activate", self._on_toggle_pin_activate)
        group.add_action(toggle_pin_action)

        delete_folder_action = Gio.SimpleAction.new("delete-folder", None)
        delete_folder_action.connect("activate", self._on_delete_folder_activate)
        group.add_action(delete_folder_action)

        rename_folder_action = Gio.SimpleAction.new("rename-folder", None)
        rename_folder_action.connect("activate", self._on_rename_folder_activate)
        group.add_action(rename_folder_action)

        reveal_folder_action = Gio.SimpleAction.new("reveal-folder", None)
        reveal_folder_action.connect("activate", self._on_reveal_folder_activate)
        group.add_action(reveal_folder_action)

        toggle_folder_pin_action = Gio.SimpleAction.new("toggle-folder-pin", None)
        toggle_folder_pin_action.connect("activate", self._on_toggle_folder_pin_activate)
        group.add_action(toggle_folder_pin_action)

        copy_folder_path_action = Gio.SimpleAction.new("copy-folder-path", None)
        copy_folder_path_action.connect("activate", self._on_copy_folder_path_activate)
        group.add_action(copy_folder_path_action)

        self._folder_popover = Gtk.PopoverMenu()
        self._folder_popover.set_parent(self)
        self._folder_popover.set_has_arrow(False)

        self.insert_action_group("docpanel", group)

    def _setup_pane_context_menu(self):
        """Right-click on empty area of the document pane."""
        self._pane_popover = Gtk.PopoverMenu()
        self._pane_popover.set_parent(self)
        self._pane_popover.set_has_arrow(False)
        self._pane_context_rect = Gdk.Rectangle()

        menu = Gio.Menu()
        menu.append(_("Create new Document here"), "docpane.new-document")
        menu.append(_("Refresh"), "docpane.refresh")
        self._pane_popover.set_menu_model(menu)

        new_doc_action = Gio.SimpleAction.new("new-document", None)
        new_doc_action.connect("activate", self._on_new_document_activate)
        group = Gio.SimpleActionGroup()
        group.add_action(new_doc_action)

        pane_refresh_action = Gio.SimpleAction.new("refresh", None)
        pane_refresh_action.connect("activate", lambda *_: self.refresh())
        group.add_action(pane_refresh_action)

        self.insert_action_group("docpane", group)

        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_pane_right_click)
        self._scrolled.add_controller(gesture)

        gesture2 = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture2.connect("pressed", self._on_pane_right_click)
        self._empty.add_controller(gesture2)

    def _on_pane_right_click(self, gesture, _n_press, x, y):
        widget = gesture.get_widget()
        src_point = Graphene.Point()
        src_point.x = x
        src_point.y = y
        success, dest_point = widget.compute_point(self, src_point)
        if success:
            px, py = dest_point.x, dest_point.y
        else:
            px, py = x, y

        self._pane_context_rect.x = int(px)
        self._pane_context_rect.y = int(py)
        self._pane_context_rect.width = 1
        self._pane_context_rect.height = 1
        self._pane_popover.set_pointing_to(self._pane_context_rect)
        self._pane_popover.popup()

    def _on_new_document_activate(self, *_args):
        parent_dir = self._browsing_folder or self._settings.root_directory

        dialog = Adw.AlertDialog(heading=_("New Document"))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        entry = Gtk.Entry(text=_("Untitled.md"))
        entry.set_activates_default(True)
        entry.connect("map", self._focus_and_select, 0, entry.get_text().rfind("."))
        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_new_document_response, entry, parent_dir)
        dialog.present(self.get_root())

    def _on_new_document_response(self, _dialog, response, entry, parent_dir):
        if response != "create":
            return
        name = entry.get_text().strip()
        if not name:
            return
        if not name.lower().endswith(".md"):
            name += ".md"
        path = os.path.join(parent_dir, name)
        if os.path.exists(path):
            win = self.get_root()
            if hasattr(win, "show_toast"):
                win.show_toast(_("\u201c{name}\u201d already exists").format(name=name),
                               "warning")
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {os.path.splitext(name)[0]}\n")
        except OSError:
            return
        self.refresh()

    def _build_folder_context_menu(self):
        is_pinned = (
            self._settings.is_folder_pinned(self._context_folder_path)
            if self._context_folder_path else False
        )
        pin_section = Gio.Menu()
        pin_section.append(_("Unpin") if is_pinned else _("Pin to Top"),
                           "docpanel.toggle-folder-pin")

        action_section = Gio.Menu()
        action_section.append(_("Rename"), "docpanel.rename-folder")
        action_section.append(_("Delete Folder"), "docpanel.delete-folder")
        action_section.append(_("Reveal in File Manager"), "docpanel.reveal-folder")

        path_section = Gio.Menu()
        path_section.append(_("Copy Path"), "docpanel.copy-folder-path")

        menu = Gio.Menu()
        menu.append_section(None, pin_section)
        menu.append_section(None, action_section)
        menu.append_section(None, path_section)
        return menu

    def _on_folder_row_right_click(self, gesture, _n_press, x, y, row):
        self._context_folder_path = row._folder_path
        self._folder_popover.set_menu_model(self._build_folder_context_menu())

        src_point = Graphene.Point()
        src_point.x = x
        src_point.y = y
        success, dest_point = row.compute_point(self, src_point)
        if success:
            px, py = dest_point.x, dest_point.y
        else:
            px, py = x, y

        self._context_rect.x = int(px)
        self._context_rect.y = int(py)
        self._context_rect.width = 1
        self._context_rect.height = 1
        self._folder_popover.set_pointing_to(self._context_rect)
        self._folder_popover.popup()

    def _is_dir_empty(self, path):
        try:
            for entry in os.scandir(path):
                if not entry.name.startswith("."):
                    return False
        except OSError:
            pass
        return True

    def _on_delete_folder_activate(self, *_args):
        if not self._context_folder_path:
            return
        name = os.path.basename(self._context_folder_path)

        if not self._is_dir_empty(self._context_folder_path):
            dialog = Adw.AlertDialog(
                heading=_("Folder is not empty"),
                body=_("\u201c{name}\u201d still contains files or folders.\n"
                       "Remove its contents first.").format(name=name),
            )
            dialog.add_response("ok", _("OK"))
            dialog.set_default_response("ok")
            dialog.set_close_response("ok")
            dialog.present(self.get_root())
            return

        dialog = Adw.AlertDialog(
            heading=_("Delete Folder?"),
            body=_("\u201c{name}\u201d will be deleted.").format(name=name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_folder_response, self._context_folder_path)
        dialog.present(self.get_root())

    def _on_delete_folder_response(self, _dialog, response, path):
        if response != "delete":
            return
        try:
            os.rmdir(path)
        except OSError:
            return
        self.refresh()

    def _on_rename_folder_activate(self, *_args):
        if not self._context_folder_path:
            return
        name = os.path.basename(self._context_folder_path)
        dialog = Adw.AlertDialog(
            heading=_("Rename"),
            body=_("Enter a new name for \u201c{name}\u201d:").format(name=name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("rename", _("Rename"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        entry = Gtk.Entry(text=name)
        entry.set_activates_default(True)
        entry.connect("map", self._focus_and_select, 0, len(name))
        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_rename_folder_response, self._context_folder_path, entry)
        dialog.present(self.get_root())

    def _on_rename_folder_response(self, _dialog, response, old_path, entry):
        if response != "rename":
            return
        new_name = entry.get_text().strip()
        old_name = os.path.basename(old_path)
        if not new_name or new_name == old_name:
            return
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if os.path.exists(new_path):
            win = self.get_root()
            if hasattr(win, "show_toast"):
                win.show_toast(_("\u201c{name}\u201d already exists").format(name=new_name),
                               "warning")
            return
        try:
            os.rename(old_path, new_path)
        except OSError:
            return
        self.refresh()

    def _on_reveal_folder_activate(self, *_args):
        if not self._context_folder_path:
            return
        gfile = Gio.File.new_for_path(self._context_folder_path)
        launcher = Gtk.FileLauncher.new(gfile)
        launcher.open_containing_folder(self.get_root(), None, None)

    def _on_toggle_folder_pin_activate(self, *_args):
        if not self._context_folder_path:
            return
        self._settings.toggle_folder_pin(self._context_folder_path)
        self.refresh()

    def _on_copy_folder_path_activate(self, *_args):
        if not self._context_folder_path:
            return
        Gdk.Display.get_default().get_clipboard().set(self._context_folder_path)
        win = self.get_root()
        if hasattr(win, "show_toast"):
            win.show_toast(_("Path copied to clipboard"), "success")

    def _on_row_right_click(self, gesture, _n_press, x, y, row):
        self._context_path = row._file_path

        # Rebuild menu to reflect current pin state
        self._popover.set_menu_model(self._build_context_menu(row._file_path))

        # Compute position relative to self (popover parent)
        src_point = Graphene.Point()
        src_point.x = x
        src_point.y = y
        success, dest_point = row.compute_point(self, src_point)
        if success:
            px, py = dest_point.x, dest_point.y
        else:
            px, py = x, y

        self._context_rect.x = int(px)
        self._context_rect.y = int(py)
        self._context_rect.width = 1
        self._context_rect.height = 1
        self._popover.set_pointing_to(self._context_rect)
        self._popover.popup()

    def _on_toggle_pin_activate(self, *_args):
        if not self._context_path:
            return
        self._settings.toggle_pin(self._context_path)
        self.refresh()

    def _on_pin_icon_clicked(self, _btn, path):
        self._settings.toggle_pin(path)
        self.refresh()

    def _on_open_with_activate(self, *_args):
        if not self._context_path:
            return

        # Gather candidate apps: markdown type first, fall back to plain text
        apps, seen = [], set()
        for mime in ("text/markdown", "text/plain"):
            for app in Gio.AppInfo.get_recommended_for_type(mime):
                aid = app.get_id()
                if aid and aid not in seen and "stenmark" not in aid:
                    apps.append(app)
                    seen.add(aid)

        if not apps:
            return

        popover = Gtk.Popover()
        popover.set_parent(self)
        popover.set_has_arrow(True)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            margin_start=4,
            margin_end=4,
            margin_top=4,
            margin_bottom=4,
        )

        for app in apps:
            btn = Gtk.Button()
            btn.add_css_class("flat")

            row_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=10,
                margin_start=6,
                margin_end=6,
                margin_top=4,
                margin_bottom=4,
            )
            icon = app.get_icon()
            if icon:
                img = Gtk.Image.new_from_gicon(icon)
            else:
                img = Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
            img.set_icon_size(Gtk.IconSize.NORMAL)
            row_box.append(img)
            row_box.append(Gtk.Label(label=app.get_display_name(), xalign=0))
            btn.set_child(row_box)
            btn.connect("clicked", self._launch_with_app, app, popover)
            box.append(btn)

        popover.set_child(box)
        popover.set_pointing_to(self._context_rect)
        popover.popup()

    def _launch_with_app(self, _btn, app, popover):
        popover.popdown()
        if not self._context_path:
            return
        uri = Gio.File.new_for_path(self._context_path).get_uri()
        try:
            app.launch_uris([uri], None)
        except Exception:  # nosec B110
            pass

    def _on_reveal_activate(self, *_args):
        if not self._context_path:
            return
        gfile = Gio.File.new_for_path(self._context_path)
        launcher = Gtk.FileLauncher.new(gfile)
        launcher.open_containing_folder(self.get_root(), None, None)

    def _on_copy_path_activate(self, *_args):
        if not self._context_path:
            return
        Gdk.Display.get_default().get_clipboard().set(self._context_path)
        win = self.get_root()
        if hasattr(win, "show_toast"):
            win.show_toast(_("Path copied to clipboard"), "success")

    def _on_trash_activate(self, *_args):
        if not self._context_path:
            return
        name = os.path.basename(self._context_path)
        dialog = Adw.AlertDialog(
            heading=_("Move to Trash?"),
            body=_("\u201c{name}\u201d will be moved to the trash.").format(name=name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("trash", _("Move to Trash"))
        dialog.set_response_appearance("trash", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_trash_response, self._context_path)
        dialog.present(self.get_root())

    def _on_trash_response(self, _dialog, response, path):
        if response != "trash":
            return
        gfile = Gio.File.new_for_path(path)
        try:
            gfile.trash(None)
        except Exception:
            return
        self.emit("file-trashed", path)
        self.refresh()

    def _on_move_to_folder_activate(self, *_args):
        if not self._context_path:
            return
        root = self._settings.root_directory
        subdirs = _collect_subdirs(root)
        if not subdirs:
            return  # nowhere to move to

        name = os.path.basename(self._context_path)
        current_dir = os.path.dirname(self._context_path)

        folder_paths = [root] + [p for p, _n in subdirs]
        folder_names = [_("No Folder")] + [n for _p, n in subdirs]

        dialog = Adw.AlertDialog(
            heading=_("Move to Folder"),
            body=_("Choose a destination folder for \u201c{name}\u201d:").format(name=name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("move", _("Move"))
        dialog.set_response_appearance("move", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("move")
        dialog.set_close_response("cancel")

        dropdown = Gtk.DropDown.new_from_strings(folder_names)
        dropdown.set_valign(Gtk.Align.CENTER)
        pre = folder_paths.index(current_dir) if current_dir in folder_paths else 0
        dropdown.set_selected(pre)

        dialog.set_extra_child(dropdown)
        dialog.connect("response", self._on_move_to_folder_response,
                       self._context_path, dropdown, folder_paths)
        dialog.present(self.get_root())

    def _on_move_to_folder_response(self, _dialog, response, old_path, dropdown, folder_paths):
        if response != "move":
            return
        dest_dir = folder_paths[dropdown.get_selected()]
        if dest_dir == os.path.dirname(old_path):
            return
        new_path = os.path.join(dest_dir, os.path.basename(old_path))
        if os.path.exists(new_path):
            win = self.get_root()
            if hasattr(win, "show_toast"):
                win.show_toast(_("A file with that name already exists in the "
                                 "destination folder"), "warning")
            return
        try:
            os.rename(old_path, new_path)
        except OSError:
            return
        self.emit("file-renamed", old_path, new_path)
        self.refresh()

    def _on_rename_activate(self, *_args):
        if not self._context_path:
            return
        name = os.path.basename(self._context_path)
        dialog = Adw.AlertDialog(
            heading=_("Rename"),
            body=_("Enter a new name for \u201c{name}\u201d:").format(name=name),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("rename", _("Rename"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        entry = Gtk.Entry(text=name)
        entry.set_activates_default(True)
        dot = name.rfind(".")
        sel_end = dot if dot > 0 else len(name)
        entry.connect("map", self._focus_and_select, 0, sel_end)
        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_rename_response, self._context_path, entry)
        dialog.present(self.get_root())

    @staticmethod
    def _focus_and_select(entry, start, end):
        entry.grab_focus()
        entry.select_region(start, end)

    def _on_rename_response(self, _dialog, response, old_path, entry):
        if response != "rename":
            return
        new_name = entry.get_text().strip()
        old_name = os.path.basename(old_path)
        if not new_name or new_name == old_name:
            return
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if os.path.exists(new_path):
            win = self.get_root()
            if hasattr(win, "show_toast"):
                win.show_toast(_("\u201c{name}\u201d already exists").format(name=new_name),
                               "warning")
            return
        try:
            os.rename(old_path, new_path)
        except OSError:
            return
        self.emit("file-renamed", old_path, new_path)
        self.refresh()

    # ---- Public ---------------------------------------------------------

    @property
    def is_drilled_in(self):
        """True when the user has navigated into a subfolder."""
        if not self._browsing_folder or not self._current_folder:
            return False
        if self._current_folder in (Sidebar.ALL_DOCUMENTS, Sidebar.NO_FOLDER):
            return False
        return self._browsing_folder != self._current_folder

    def navigate_back(self):
        """Go up one level in the drilled-in folder hierarchy."""
        if not self.is_drilled_in:
            return
        parent = os.path.dirname(self._browsing_folder)
        self._navigate_to(parent)

    def refresh(self):
        if self._current_folder and self._current_folder.startswith("tag:"):
            self.show_folder(self._current_folder)
        elif self._current_folder in (Sidebar.ALL_DOCUMENTS, Sidebar.NO_FOLDER):
            self.show_folder(self._current_folder)
        elif self._browsing_folder and self._browsing_folder != self._current_folder:
            # Drilled into a subfolder — refresh in place
            self._clear()
            self._show_single_folder(self._browsing_folder)
        elif self._current_folder:
            self.show_folder(self._current_folder)
