# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gio, GObject, Gdk, Graphene

from stenmark.i18n import _


def _count_md_files(dir_path):
    """Recursively count .md files in a directory."""
    count = 0
    try:
        for entry in os.scandir(dir_path):
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                count += _count_md_files(entry.path)
            elif entry.name.lower().endswith(".md"):
                count += 1
    except OSError:
        pass
    return count


def _count_root_md_files(dir_path):
    """Count .md files directly in dir_path (non-recursive)."""
    count = 0
    try:
        for entry in os.scandir(dir_path):
            if entry.name.startswith("."):
                continue
            if not entry.is_dir(follow_symlinks=False) and entry.name.lower().endswith(".md"):
                count += 1
    except OSError:
        pass
    return count


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


class Sidebar(Gtk.Box):
    __gsignals__ = {
        "folder-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "file-created": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "search-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "tag-filter-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "open-root-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    # Special sentinels
    ALL_DOCUMENTS = "__ALL__"
    NO_FOLDER = "__ROOT__"

    def __init__(self, settings, tag_index=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._settings = settings
        self._tag_index = tag_index
        self._context_path = None
        self._selected_path = None

        self.set_size_request(220, -1)

        scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._listbox = Gtk.ListBox()
        self._listbox.add_css_class("navigation-sidebar")
        self._listbox.connect("row-activated", self._on_row_selected)

        scrolled.set_child(self._listbox)
        self._scrolled = scrolled
        self.append(scrolled)

        # Bottom action bar
        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        action_bar.add_css_class("toolbar")

        new_file_btn = Gtk.Button(
            icon_name="stenmark-document-new-symbolic",
            tooltip_text=_("New Document"),
            hexpand=True,
        )
        new_file_btn.connect("clicked", lambda _b: self._new_file(self._active_dir()))

        new_dir_btn = Gtk.Button(
            icon_name="stenmark-folder-new-symbolic",
            tooltip_text=_("New Folder"),
            hexpand=True,
        )
        new_dir_btn.connect("clicked", lambda _b: self._new_directory(self._settings.root_directory))

        tag_btn = Gtk.Button(
            icon_name="stenmark-tag-symbolic",
            tooltip_text=_("Filter by Tag"),
            hexpand=True,
        )
        tag_btn.connect("clicked", lambda _b: self.emit("tag-filter-requested"))

        search_btn = Gtk.Button(
            icon_name="stenmark-system-search-symbolic",
            tooltip_text=_("Search All Documents"),
            hexpand=True,
        )
        search_btn.connect("clicked", lambda _b: self.emit("search-requested"))

        action_bar.append(new_dir_btn)
        action_bar.append(new_file_btn)
        action_bar.append(tag_btn)
        action_bar.append(search_btn)
        self._action_bar = action_bar
        self.append(action_bar)

        # Outside-root placeholder (shown when viewed file is not in root)
        self._outside_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            vexpand=True,
            hexpand=True,
            visible=False,
        )
        open_root_btn = Gtk.Button(
            label=_("Open root folder"),
            css_classes=["suggested-action", "pill"],
            halign=Gtk.Align.CENTER,
        )
        open_root_btn.connect("clicked", lambda _b: self.emit("open-root-requested"))
        self._outside_box.append(open_root_btn)
        self.append(self._outside_box)

        self._setup_context_menu()
        self._populate()

    def _active_dir(self):
        """Return the currently selected folder path (or root for All Documents)."""
        if self._selected_path and self._selected_path not in (self.ALL_DOCUMENTS, self.NO_FOLDER):
            return self._selected_path
        return self._settings.root_directory

    # ---- Populate -------------------------------------------------------

    def _populate(self):
        # Block selection signal while rebuilding to avoid spurious emissions
        self._listbox.disconnect_by_func(self._on_row_selected)

        while True:
            row = self._listbox.get_row_at_index(0)
            if row is None:
                break
            self._listbox.remove(row)
        root = self._settings.root_directory

        # "All Documents" row
        total = _count_md_files(root)
        row = self._make_row(
            _("All Documents"),
            "stenmark-document-all-symbolic",
            total,
            self.ALL_DOCUMENTS,
        )
        self._listbox.append(row)

        # "No Folder" row — only when there are root-level files
        root_count = _count_root_md_files(root)
        if root_count:
            row = self._make_row(
                _("No Folder"),
                "stenmark-folder-striped-symbolic",
                root_count,
                self.NO_FOLDER,
            )
            self._listbox.append(row)

        # One row per subdirectory — pinned folders first
        subdirs = _collect_subdirs(root)
        pinned_dirs = [(p, n) for p, n in subdirs if self._settings.is_folder_pinned(p)]
        unpinned_dirs = [(p, n) for p, n in subdirs if not self._settings.is_folder_pinned(p)]
        for dir_path, dir_name in pinned_dirs + unpinned_dirs:
            count = _count_md_files(dir_path)
            icon = "stenmark-pin-symbolic" if self._settings.is_folder_pinned(dir_path) else "stenmark-folder-symbolic"
            row = self._make_row(dir_name, icon, count, dir_path)
            self._listbox.append(row)

        # Tags section
        if self._tag_index and self._settings.get("show_sidebar_tags"):
            all_tags = self._tag_index.all_tags()
            if all_tags:
                divider_box = Gtk.Box(
                    orientation=Gtk.Orientation.VERTICAL,
                    spacing=0,
                )
                divider_box.append(Gtk.Separator(margin_top=6, margin_bottom=4))
                divider_box.append(Gtk.Label(
                    label=_("Tags"),
                    xalign=0,
                    css_classes=["dim-label", "caption"],
                    margin_start=8,
                    margin_bottom=2,
                ))
                divider_row = Gtk.ListBoxRow(child=divider_box)
                divider_row.set_selectable(False)
                divider_row.set_activatable(False)
                divider_row.set_can_focus(False)
                divider_row.set_can_target(False)
                divider_row.add_css_class("sidebar-divider")
                self._listbox.append(divider_row)

                for tag in all_tags:
                    count = self._tag_index.tag_count(tag)
                    row = self._make_row(
                        tag,
                        "stenmark-tag-symbolic",
                        count,
                        f"tag:{tag}",
                    )
                    self._listbox.append(row)

        # Reconnect and select "All Documents" by default
        self._listbox.connect("row-activated", self._on_row_selected)
        first = self._listbox.get_row_at_index(0)
        if first:
            self._listbox.select_row(first)

    def _make_row(self, label_text, icon_name, count, path):
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            margin_start=8,
            margin_end=8,
            margin_top=8,
            margin_bottom=8,
        )

        icon = Gtk.Image(icon_name=icon_name)
        name_label = Gtk.Label(
            label=label_text,
            xalign=0,
            hexpand=True,
            css_classes=["heading"],
        )
        count_label = Gtk.Label(
            label=str(count),
            css_classes=["dim-label", "caption"],
            valign=Gtk.Align.CENTER,
        )

        box.append(icon)
        box.append(name_label)
        box.append(count_label)

        row = Gtk.ListBoxRow(child=box)
        row._folder_path = path
        return row

    # ---- Selection ------------------------------------------------------

    def _on_row_selected(self, _listbox, row):
        if row is None:
            return
        path = row._folder_path
        self._selected_path = path
        self.emit("folder-selected", path)

    # ---- Context menu ---------------------------------------------------

    def _setup_context_menu(self):
        self._popover = Gtk.PopoverMenu()
        self._popover.set_parent(self)
        self._popover.set_has_arrow(False)

        group = Gio.SimpleActionGroup()

        rename_action = Gio.SimpleAction.new("rename", None)
        rename_action.connect("activate", self._on_rename_activate)
        group.add_action(rename_action)
        self._rename_action = rename_action

        trash_action = Gio.SimpleAction.new("trash", None)
        trash_action.connect("activate", self._on_trash_activate)
        group.add_action(trash_action)
        self._trash_action = trash_action

        reveal_action = Gio.SimpleAction.new("reveal", None)
        reveal_action.connect("activate", self._on_reveal_activate)
        group.add_action(reveal_action)
        self._reveal_action = reveal_action

        new_file_action = Gio.SimpleAction.new("new-file", None)
        new_file_action.connect("activate", self._on_new_file_activate)
        group.add_action(new_file_action)

        new_dir_action = Gio.SimpleAction.new("new-dir", None)
        new_dir_action.connect("activate", self._on_new_dir_activate)
        group.add_action(new_dir_action)

        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", lambda *_: self.refresh())
        group.add_action(refresh_action)

        copy_path_action = Gio.SimpleAction.new("copy-path", None)
        copy_path_action.connect("activate", self._on_copy_path_activate)
        group.add_action(copy_path_action)
        self._copy_path_action = copy_path_action

        pin_action = Gio.SimpleAction.new("pin", None)
        pin_action.connect("activate", self._on_pin_activate)
        group.add_action(pin_action)
        self._pin_action = pin_action

        self.insert_action_group("sidebar", group)

        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_right_click)
        self._listbox.add_controller(gesture)

    def _build_menu(self, is_folder, is_pinned):
        menu = Gio.Menu()

        if is_folder:
            pin_section = Gio.Menu()
            pin_section.append(_("Unpin") if is_pinned else _("Pin to Top"), "sidebar.pin")
            menu.append_section(None, pin_section)

        item_section = Gio.Menu()
        item_section.append(_("Rename"), "sidebar.rename")
        item_section.append(_("Delete Folder"), "sidebar.trash")
        item_section.append(_("Reveal in File Manager"), "sidebar.reveal")
        menu.append_section(None, item_section)

        new_section = Gio.Menu()
        new_section.append(_("New Document"), "sidebar.new-file")
        new_section.append(_("New Folder"), "sidebar.new-dir")
        menu.append_section(None, new_section)

        misc_section = Gio.Menu()
        if is_folder:
            misc_section.append(_("Copy Path"), "sidebar.copy-path")
        misc_section.append(_("Refresh"), "sidebar.refresh")
        menu.append_section(None, misc_section)

        return menu

    def _on_right_click(self, gesture, _n_press, x, y):
        row = self._listbox.get_row_at_y(int(y))
        is_folder = False
        if row:
            path = row._folder_path
            is_folder = path not in (self.ALL_DOCUMENTS, self.NO_FOLDER)
            self._context_path = path if is_folder else None
        else:
            self._context_path = None

        self._rename_action.set_enabled(is_folder)
        self._trash_action.set_enabled(is_folder)
        self._reveal_action.set_enabled(is_folder)
        self._copy_path_action.set_enabled(is_folder)
        self._pin_action.set_enabled(is_folder)

        is_pinned = is_folder and self._settings.is_folder_pinned(self._context_path)
        self._popover.set_menu_model(self._build_menu(is_folder, is_pinned))

        # Compute position relative to self (popover parent) so the
        # popover is not constrained to the listbox allocation.
        src_point = Graphene.Point()
        src_point.x = x
        src_point.y = y
        success, dest_point = self._listbox.compute_point(self, src_point)
        if success:
            px, py = dest_point.x, dest_point.y
        else:
            px, py = x, y

        rect = Gdk.Rectangle()
        rect.x = int(px)
        rect.y = int(py)
        rect.width = 1
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    # ---- Reveal ---------------------------------------------------------

    def _on_reveal_activate(self, *_args):
        if not self._context_path:
            return
        gfile = Gio.File.new_for_path(self._context_path)
        launcher = Gtk.FileLauncher.new(gfile)
        launcher.open_containing_folder(self.get_root(), None, None)

    # ---- Copy path ------------------------------------------------------

    def _on_copy_path_activate(self, *_args):
        if not self._context_path:
            return
        Gdk.Display.get_default().get_clipboard().set(self._context_path)
        win = self.get_root()
        if hasattr(win, "show_toast"):
            win.show_toast(_("Path copied to clipboard"), "success")

    # ---- Pin ------------------------------------------------------------

    def _on_pin_activate(self, *_args):
        if not self._context_path:
            return
        self._settings.toggle_folder_pin(self._context_path)
        self.refresh()

    # ---- Trash ----------------------------------------------------------

    def _is_dir_empty(self, path):
        """Check if directory has no visible (non-dot) entries."""
        try:
            for entry in os.scandir(path):
                if not entry.name.startswith("."):
                    return False
        except OSError:
            pass
        return True

    def _on_trash_activate(self, *_args):
        if not self._context_path:
            return
        name = os.path.basename(self._context_path)

        if os.path.isdir(self._context_path) and not self._is_dir_empty(self._context_path):
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
        dialog.add_response("trash", _("Delete"))
        dialog.set_response_appearance("trash", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_trash_response, self._context_path)
        dialog.present(self.get_root())

    def _on_trash_response(self, _dialog, response, path):
        if response != "trash":
            return
        try:
            os.rmdir(path)
        except OSError:
            return
        self.refresh()

    # ---- Rename ---------------------------------------------------------

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
        entry.connect("map", self._focus_and_select, 0, len(name))
        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_rename_response, self._context_path, entry)
        dialog.present(self.get_root())

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
                win.show_toast(f"\u201c{new_name}\u201d already exists", "warning")
            return
        try:
            os.rename(old_path, new_path)
        except OSError:
            return
        self.refresh()

    # ---- New file / folder ----------------------------------------------

    def _context_dir(self):
        if self._context_path and self._context_path not in (self.ALL_DOCUMENTS, self.NO_FOLDER):
            return self._context_path
        return self._settings.root_directory

    def _on_new_file_activate(self, *_args):
        self._new_file(self._context_dir())

    def _on_new_dir_activate(self, *_args):
        self._new_directory(self._context_dir())

    @staticmethod
    def _focus_and_select(entry, start, end):
        entry.grab_focus()
        entry.select_region(start, end)

    def _new_file(self, parent_dir):
        root = self._settings.root_directory
        subdirs = _collect_subdirs(root)

        # folder_paths[i] maps to the dropdown index
        folder_paths = [root] + [p for p, _n in subdirs]
        folder_names = [_("No Folder")] + [n for _p, n in subdirs]

        dialog = Adw.AlertDialog(heading=_("New Document"))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        entry = Gtk.Entry(text=_("Untitled.md"))
        entry.set_activates_default(True)
        entry.connect("map", self._focus_and_select, 0, entry.get_text().rfind("."))
        vbox.append(entry)

        folder_dropdown = None
        if subdirs:
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                margin_top=2,
            )
            lbl = Gtk.Label(label=_("Folder"), xalign=0, hexpand=True)
            lbl.add_css_class("dim-label")
            folder_dropdown = Gtk.DropDown.new_from_strings(folder_names)
            folder_dropdown.set_valign(Gtk.Align.CENTER)
            pre = folder_paths.index(parent_dir) if parent_dir in folder_paths else 0
            folder_dropdown.set_selected(pre)
            row.append(lbl)
            row.append(folder_dropdown)
            vbox.append(row)

        dialog.set_extra_child(vbox)
        dialog.connect(
            "response", self._on_new_file_response,
            entry, folder_dropdown, folder_paths,
        )
        dialog.present(self.get_root())

    def _on_new_file_response(self, _dialog, response, entry, folder_dropdown, folder_paths):
        if response != "create":
            return
        name = entry.get_text().strip()
        if not name:
            return
        if not name.lower().endswith(".md"):
            name += ".md"
        parent_dir = (
            folder_paths[folder_dropdown.get_selected()]
            if folder_dropdown is not None
            else folder_paths[0]
        )
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
        self.emit("file-created", path)

    def _new_directory(self, parent_dir):
        dialog = Adw.AlertDialog(
            heading=_("New Folder"),
            body=_("Enter a name for the new folder:"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        default_name = _("New Folder")
        entry = Gtk.Entry(text=default_name)
        entry.set_activates_default(True)
        entry.connect("map", self._focus_and_select, 0, len(default_name))
        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_new_dir_response, parent_dir, entry)
        dialog.present(self.get_root())

    def _on_new_dir_response(self, _dialog, response, parent_dir, entry):
        if response != "create":
            return
        name = entry.get_text().strip()
        if not name:
            return
        path = os.path.join(parent_dir, name)
        if os.path.exists(path):
            win = self.get_root()
            if hasattr(win, "show_toast"):
                win.show_toast(_("\u201c{name}\u201d already exists").format(name=name),
                               "warning")
            return
        try:
            os.makedirs(path)
        except OSError:
            return
        self.refresh()

    # ---- Public ---------------------------------------------------------

    def refresh(self):
        self._settings.cleanup_stale_pins()
        self.set_outside_root(False)
        self._populate()
        self.emit("changed")

    def refresh_tags(self):
        """Rebuild only the tag rows in the sidebar (no selection change)."""
        if not self._tag_index or not self._settings.get("show_sidebar_tags"):
            return
        # Remove existing tag rows (divider + tag rows at the end)
        while True:
            row = self._listbox.get_last_child()
            if row is None:
                break
            if hasattr(row, '_folder_path') and row._folder_path.startswith("tag:"):
                self._listbox.remove(row)
            elif row.has_css_class("sidebar-divider"):
                self._listbox.remove(row)
                break
            else:
                break
        # Re-add tag section
        all_tags = self._tag_index.all_tags()
        if all_tags:
            divider_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=0,
            )
            divider_box.append(Gtk.Separator(margin_top=6, margin_bottom=4))
            divider_box.append(Gtk.Label(
                label=_("Tags"),
                xalign=0,
                css_classes=["dim-label", "caption"],
                margin_start=8,
                margin_bottom=2,
            ))
            divider_row = Gtk.ListBoxRow(child=divider_box)
            divider_row.set_selectable(False)
            divider_row.set_activatable(False)
            divider_row.set_can_focus(False)
            divider_row.set_can_target(False)
            divider_row.add_css_class("sidebar-divider")
            self._listbox.append(divider_row)

            for tag in all_tags:
                count = self._tag_index.tag_count(tag)
                row = self._make_row(
                    tag,
                    "stenmark-tag-symbolic",
                    count,
                    f"tag:{tag}",
                )
                self._listbox.append(row)

    def set_outside_root(self, outside):
        if outside:
            self._scrolled.set_visible(False)
            self._action_bar.set_visible(False)
            self._outside_box.set_visible(True)
        else:
            self._outside_box.set_visible(False)
            self._scrolled.set_visible(True)
            self._action_bar.set_visible(True)

    def get_selected_folder(self):
        return self._selected_path
