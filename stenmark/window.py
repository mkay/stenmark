# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import os
import re

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Gio

from stenmark import APP_NAME, VERSION
from stenmark.i18n import _, ngettext
from stenmark.sidebar import Sidebar, _collect_tree
from stenmark.document_panel import DocumentPanel
from stenmark.viewer import MarkdownViewer
from stenmark.editor import MarkdownEditor
from stenmark.welcome import WelcomeView
from stenmark.search_panel import SearchPanel
from stenmark.tag_index import TagIndex
from stenmark.tag_panel import TagPanel
from stenmark.frontmatter import read_tags, update_tags
from stenmark.markdown_renderer import MarkdownRenderer
from stenmark.note_file import NoteChanged, moved_path, read_note, save_note
from stenmark.root_selector import RootSelector


# Prototype switch for the sidebar's root-folder selector. True gives the
# drill-down popover from root_selector.py; False restores the flat
# GtkDropDown, which is kept intact below.
ROOT_DRILLDOWN = True


class RootFolder(GObject.Object):
    """One entry in the root-folder selector."""

    # A custom factory replaces GtkDropDown's own checkmark, so the rows
    # track the current folder themselves.
    selected = GObject.Property(type=bool, default=False)

    def __init__(self, name, depth):
        super().__init__()
        self.name = name
        self.depth = depth


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, settings, open_file=None):
        super().__init__(application=application)
        self._settings = settings
        self._current_file = None
        self._editing = False
        self._watcher = None
        self._preview_timeout_id = None
        self._toc_headings = []
        self._nav_history = []   # list of file paths
        self._nav_index = -1     # current position in history
        # (line, word) the editor should open at, set by double-click in the reader
        self._pending_edit_pos = None
        # Sidebar visibility to put back when edit mode ends; None when we
        # did not hide it ourselves.
        self._renderer = MarkdownRenderer()
        # The note as it stood when editing began or was last saved
        self._note = None
        self._sidebar_before_edit = None
        # Sidebar visibility to return to when the note-only view ends
        self._sidebar_before_note_only = True
        # Set while we move the split views ourselves, not the user
        self._layout_syncing = False

        self.set_default_size(settings.window_width, settings.window_height)
        self.set_title(APP_NAME)

        # Restore last navigated folder if the feature is enabled
        # (but not if a CLI path override is already set)
        if "root_directory" not in settings._overrides and settings.get("remember_last_folder"):
            last = settings.get("last_root_folder")
            if last and os.path.isdir(last):
                settings.set_override("root_directory", last)

        self._tag_index = TagIndex(settings.root_directory)

        self._build_ui()
        self._connect_signals()
        self._setup_actions()
        self._show_default_folder()
        self._on_layout_changed(None, None)
        self.connect("close-request", self._on_close_request)

        if open_file:
            self.open_file(open_file)
        if settings.load_failed:
            self.show_toast(_("settings.json can\u2019t be read, so changes to settings "
                              "won\u2019t be saved"), "error", timeout=0)

    # A property so the status-bar readout can't fall out of step with it:
    # edit mode ends both in _close_editor() and when the open note is
    # trashed, and the readout has to dim with every one of them.
    @property
    def _editing(self):
        return self._editing_state

    @_editing.setter
    def _editing(self, value):
        self._editing_state = value
        # __init__ sets this before the status bar exists.
        if hasattr(self, "_typewriter_btn"):
            self._update_typewriter_label()
            # Tags are written to the file, which the editor would then
            # overwrite or report as a conflict.
            self._tags_btn.set_sensitive(not value)

    def _build_ui(self):
        # === Sidebar ToolbarView ===
        sidebar_header = Adw.HeaderBar(show_end_title_buttons=False)
        # The content header already shows the app/document name; a second
        # "Stenmark" over the sidebar is just noise.
        sidebar_header.set_title_widget(Gtk.Box())

        # The "ceiling" is the configured root from settings (ignoring session overrides)
        self._root_ceiling = self._settings._data.get("root_directory", self._settings.get("root_directory"))
        # Which ceiling the drill-down has already been handed, so a plain
        # folder change refreshes its pages instead of resetting the stack.
        self._root_ceiling_shown = None

        # Root selector: the ceiling folder plus every folder beneath it.
        self._root_paths = []
        self._root_model = Gio.ListStore(item_type=RootFolder)
        # Guards the handler while we set the selection to match settings
        self._root_syncing = False
        if ROOT_DRILLDOWN:
            self._root_dropdown = RootSelector()
            self._root_dropdown.connect(
                "folder-selected", self._on_root_folder_selected
            )
        else:
            self._root_dropdown = Gtk.DropDown(
                model=self._root_model,
                tooltip_text=_("Change root folder"),
                # Lets the stylesheet reach the popup's rows, which carry the
                # dividers and their own tightened padding.
                css_classes=["root-dropdown"],
                list_factory=self._root_row_factory(indent=True),
                factory=self._root_row_factory(indent=False),
            )
            self._root_dropdown.connect("notify::selected", self._on_root_selected)
        self._rebuild_root_model()

        self._sidebar = Sidebar(self._settings, tag_index=self._tag_index)
        self._sidebar.set_root_widget(self._root_dropdown)

        # Bound to the split view's show-sidebar once that exists; a twin
        # sits in the list column's header for when this one is hidden.
        self._sidebar_btn = Gtk.ToggleButton(
            icon_name="stenmark-sidebar-symbolic",
            tooltip_text=_("Toggle sidebar"),
            active=True,
        )
        self._sidebar_btn.set_focus_on_click(False)
        sidebar_header.pack_end(self._sidebar_btn)

        sidebar_toolbar = Adw.ToolbarView()
        sidebar_toolbar.add_css_class("app-sidebar")
        sidebar_toolbar.add_top_bar(sidebar_header)
        sidebar_toolbar.set_content(self._sidebar)

        # === Content ToolbarView ===
        self._content_header = Adw.HeaderBar(show_start_title_buttons=False)

        # Note only: hides the sidebar and the document list together,
        # leftmost, as in the Mac app
        self._lists_btn = Gtk.Button(
            icon_name="stenmark-sidebar-hide-symbolic",
            tooltip_text=_("Show note only"),
        )
        self._lists_btn.set_focus_on_click(False)
        self._content_header.pack_start(self._lists_btn)

        # Edit toggle (start)
        self._edit_btn = Gtk.ToggleButton(
            icon_name="stenmark-edit-symbolic",
            tooltip_text=_("Toggle edit mode"),
            sensitive=False,
        )
        self._edit_btn.set_focus_on_click(False)
        self._content_header.pack_start(self._edit_btn)

        # Preview toggle (only visible while editing)
        # Restores whatever the user last chose
        preview_on = bool(self._settings.get("preview_enabled"))
        self._preview_btn = Gtk.ToggleButton(
            # One icon, as in the Mac app; the pressed state says it's on
            icon_name="stenmark-split-symbolic",
            tooltip_text=_("Toggle live preview"),
            active=preview_on,
            visible=False,
        )
        self._preview_btn.set_focus_on_click(False)
        self._content_header.pack_start(self._preview_btn)

        # Title
        self._title_widget = Adw.WindowTitle(title=APP_NAME, subtitle="")
        self._content_header.set_title_widget(self._title_widget)

        # Hamburger menu (rightmost end)
        menu = Gio.Menu()
        window_section = Gio.Menu()
        window_section.append(_("New Window"), "app.new-window")
        menu.append_section(None, window_section)
        file_section = Gio.Menu()
        file_section.append(_("Export to PDF"), "win.export-pdf")
        menu.append_section(None, file_section)
        prefs_section = Gio.Menu()
        prefs_section.append(_("Preferences"), "win.preferences")
        prefs_section.append(_("Support Stenmark"), "app.support")
        menu.append_section(None, prefs_section)
        about_section = Gio.Menu()
        about_section.append(_("About"), "win.about")
        menu.append_section(None, about_section)
        menu_btn = Gtk.MenuButton(
            icon_name="stenmark-open-menu-symbolic",
            menu_model=menu,
            tooltip_text=_("Menu"),
        )
        menu_btn.set_focus_on_click(False)
        self._content_header.pack_end(menu_btn)


        # Open In (visible when a file is open, disabled while editing)
        self._open_in_btn = Gtk.Button(
            icon_name="stenmark-open-with-symbolic",
            tooltip_text=_("Open in…"),
            visible=False,
        )
        self._open_in_btn.set_focus_on_click(False)
        self._content_header.pack_end(self._open_in_btn)

        # Copy as rich text (visible when a file is open)
        self._copy_rich_btn = Gtk.Button(
            icon_name="stenmark-copy-rich-text-symbolic",
            tooltip_text=_("Copy as rich text"),
            visible=False,
        )
        self._copy_rich_btn.set_focus_on_click(False)
        self._content_header.pack_end(self._copy_rich_btn)

        # Tags button (visible when a file is open)
        self._tags_btn = Gtk.Button(
            icon_name="stenmark-tag-symbolic",
            tooltip_text=_("Edit tags"),
            visible=False,
        )
        self._tags_btn.set_focus_on_click(False)
        self._content_header.pack_end(self._tags_btn)

        # Table of contents popover (visible when a file is open)
        self._toc_btn = Gtk.MenuButton(
            icon_name="stenmark-toc-symbolic",
            tooltip_text=_("Table of contents"),
            visible=False,
        )
        self._toc_btn.set_focus_on_click(False)
        self._toc_popover = Gtk.Popover()
        self._toc_popover.set_size_request(280, -1)
        self._toc_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._toc_list.add_css_class("navigation-sidebar")
        self._toc_list.connect("row-activated", self._on_toc_row_activated)
        scroll = Gtk.ScrolledWindow(
            max_content_height=400,
            propagate_natural_height=True,
        )
        scroll.set_child(self._toc_list)
        self._toc_popover.set_child(scroll)
        self._toc_btn.set_popover(self._toc_popover)
        self._content_header.pack_end(self._toc_btn)

        # Content stack
        self._stack = Gtk.Stack(hhomogeneous=False)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._welcome = WelcomeView(
            settings=self._settings,
            on_set_root=self._on_set_root_from_welcome,
            on_new_file=self._on_new_file_from_welcome,
        )
        self._stack.add_named(self._welcome, "welcome")

        self._viewer = MarkdownViewer(self._settings)
        self._stack.add_named(self._viewer, "view")

        self._editor = MarkdownEditor(self._settings)
        # Its checkboxes describe the unsaved text, not the file they'd write to
        self._preview_viewer = MarkdownViewer(self._settings, read_only_tasks=True)
        self._preview_viewer.set_visible(self._preview_btn.get_active())

        dbl = self._settings.double_click_to_edit
        self._viewer.set_edit_on_dblclick(dbl)
        self._preview_viewer.set_edit_on_dblclick(dbl)

        self._edit_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._edit_paned.set_start_child(self._editor)
        self._edit_paned.set_end_child(self._preview_viewer)
        self._edit_paned.set_resize_start_child(True)
        self._edit_paned.set_resize_end_child(True)
        self._edit_paned.set_shrink_start_child(False)
        self._edit_paned.set_shrink_end_child(False)
        self._edit_paned.set_position(self._settings.window_width // 2)
        self._stack.add_named(self._edit_paned, "edit")

        self._stack.set_visible_child_name("welcome")

        # === Status bar ===
        self._status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._status_bar.add_css_class("toolbar")
        self._status_bar.set_margin_start(12)
        self._status_bar.set_margin_end(12)
        self._status_bar.set_visible(False)

        spacer = Gtk.Box(hexpand=True)
        self._status_bar.append(spacer)
        self._word_count_label = Gtk.Label(css_classes=["caption", "dim-label"])
        self._reading_time_label = Gtk.Label(css_classes=["caption", "dim-label"])
        self._status_bar.append(self._word_count_label)
        self._status_bar.append(self._reading_time_label)

        # Typewriter belongs beside the stats: both are about the document
        # you are writing. Styled as one of them rather than as a button
        # parked in the bar — it carries its state in its text, and in view
        # mode, where it can't do anything, it is a readout and nothing more.
        # Still a real button underneath, so it keeps keyboard and screen
        # reader behaviour. Preferences stays the durable home.
        # A GtkLabel, exactly like the two stats beside it, rather than a
        # button wearing a label's clothes: libadwaita's stylesheet outranks
        # ours, so a button keeps its 16px side padding whatever we ask for,
        # and lands a half-gap further out than the stats it sits with.
        self._typewriter_btn = Gtk.Label(
            css_classes=["caption", "dim-label"],
            accessible_role=Gtk.AccessibleRole.BUTTON,
        )
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._on_typewriter_action())
        self._typewriter_btn.add_controller(click)
        self._status_bar.append(self._typewriter_btn)

        content_toolbar = Adw.ToolbarView()
        content_toolbar.add_top_bar(self._content_header)
        content_toolbar.add_bottom_bar(self._status_bar)
        content_toolbar.set_content(self._stack)

        # === Document list column ===
        self._list_header = Adw.HeaderBar(
            show_start_title_buttons=False,
            show_end_title_buttons=False,
        )
        self._list_sidebar_btn = Gtk.ToggleButton(
            icon_name="stenmark-sidebar-symbolic",
            tooltip_text=_("Toggle sidebar"),
            visible=False,
        )
        self._list_sidebar_btn.set_focus_on_click(False)
        self._list_header.pack_start(self._list_sidebar_btn)

        # Out of a subfolder, search or the tag filter
        self._list_back_btn = Gtk.Button(
            icon_name="stenmark-go-previous-symbolic",
            tooltip_text=_("Back"),
            visible=False,
        )
        self._list_back_btn.connect("clicked", self._on_list_back_clicked)
        self._list_header.pack_start(self._list_back_btn)

        self._list_title = Adw.WindowTitle()
        self._list_header.set_title_widget(self._list_title)

        self._list_stack = Gtk.Stack(hhomogeneous=False)
        self._list_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._doc_panel = DocumentPanel(self._settings, tag_index=self._tag_index)
        self._list_stack.add_named(self._doc_panel, "documents")

        self._search_panel = SearchPanel(self._settings)
        self._list_stack.add_named(self._search_panel, "search")

        self._tag_panel = TagPanel(self._settings, self._tag_index)
        self._list_stack.add_named(self._tag_panel, "tags")

        self._list_toolbar = Adw.ToolbarView()
        self._list_toolbar.add_top_bar(self._list_header)
        self._list_toolbar.set_content(self._list_stack)
        self._update_list_tint()

        # === Split views: sidebar | (list | note) ===
        self._list_split = Adw.OverlaySplitView(
            min_sidebar_width=240,
            max_sidebar_width=360,
            sidebar_width_fraction=0.32,
        )
        self._list_split.set_sidebar(self._list_toolbar)
        self._list_split.set_content(content_toolbar)

        self._split_view = Adw.OverlaySplitView()
        self._split_view.set_show_sidebar(True)
        self._split_view.set_sidebar(sidebar_toolbar)
        self._split_view.set_content(self._list_split)

        for btn in (self._sidebar_btn, self._list_sidebar_btn):
            self._split_view.bind_property(
                "show-sidebar", btn, "active",
                GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
            )

        # Narrow windows fold the columns into overlays, list first. Only the
        # last matching breakpoint applies, so the narrower one folds both.
        self.set_size_request(400, 360)
        for width, splits in (("860sp", [self._list_split]),
                              ("600sp", [self._list_split, self._split_view])):
            bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {width}"))
            for split in splits:
                bp.add_setter(split, "collapsed", True)
                bp.add_setter(split, "show-sidebar", False)
            self.add_breakpoint(bp)

        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._split_view)
        self.set_content(self._toast_overlay)

        # Mouse back/forward buttons
        mouse_ctl = Gtk.GestureClick(button=0)
        mouse_ctl.connect("pressed", self._on_mouse_button)
        self.add_controller(mouse_ctl)

        _toast_css = Gtk.CssProvider()
        _toast_css.load_from_string("""
            .toast-error-icon   { color: @error_color;   }
            .toast-success-icon { color: @success_color; }
            .toast-warning-icon { color: @warning_color; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _toast_css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _connect_signals(self):
        self._lists_btn.connect("clicked", self._on_lists_toggled)
        for split in (self._split_view, self._list_split):
            split.connect("notify::show-sidebar", self._on_layout_changed)
            split.connect("notify::collapsed", self._on_layout_changed)
        self._edit_btn.connect("toggled", self._on_edit_toggled)
        self._sidebar.connect("folder-selected", self._on_folder_selected)
        self._sidebar.connect("changed", self._on_sidebar_changed)
        self._sidebar.connect("file-created", self._on_file_created)
        self._sidebar.connect("folder-renamed", self._on_folder_renamed)
        self._sidebar.connect("search-requested", lambda _s: self._on_search(None, None))
        self._sidebar.connect("tag-filter-requested", lambda _s: self._on_tag_filter(None, None))
        self._sidebar.connect("open-root-requested", self._on_open_root_requested)
        self._doc_panel.connect("file-selected", self._on_file_selected)
        self._doc_panel.connect("file-trashed", self._on_file_trashed)
        self._doc_panel.connect("file-renamed", self._on_file_renamed)
        self._doc_panel.connect("folder-renamed", self._on_folder_renamed)
        self._doc_panel.connect("folder-navigated", self._on_folder_navigated)
        self._doc_panel.connect("tag-clicked", lambda _p, tag: self._open_tag_panel(tag))
        self._settings.connect("changed", self._on_settings_changed)
        self._editor.set_save_callback(self._on_editor_save)
        self._editor.set_preview_callback(self._on_preview_text_changed)
        self._editor.set_scroll_callback(self._on_editor_scroll)
        self._editor.set_escape_callback(self._on_editor_escape)
        self._search_panel.connect("file-selected", self._on_file_selected)
        self._search_panel.connect("close-requested", lambda _p: self._show_documents_list())
        self._search_panel.connect("tag-filter-requested", lambda _p: self._open_tag_panel())
        self._tag_panel.connect("file-selected", self._on_file_selected)
        self._tag_panel.connect("close-requested", lambda _p: self._show_documents_list())
        self._viewer.connect("link-activated", self._on_viewer_link)
        self._viewer.connect("navigate-back", lambda *_: self._navigate_back())
        self._viewer.connect("navigate-forward", lambda *_: self._navigate_forward())
        self._viewer.connect("edit-requested", self._on_edit_requested)
        self._preview_viewer.connect("link-activated", self._on_viewer_link)
        self._preview_viewer.connect("edit-requested", self._on_edit_requested_preview)
        self._preview_btn.connect("toggled", self._on_preview_toggled)
        self._copy_rich_btn.connect("clicked", self._on_copy_rich_text)
        self._open_in_btn.connect("clicked", self._on_open_in)
        self._tags_btn.connect("clicked", self._on_tags_clicked)

    def _setup_actions(self):
        prefs = Gio.SimpleAction.new("preferences", None)
        prefs.connect("activate", self._on_preferences)
        self.add_action(prefs)

        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        find = Gio.SimpleAction.new("find", None)
        find.connect("activate", self._on_find)
        self.add_action(find)
        self.get_application().set_accels_for_action("win.find", ["<Control>f"])

        edit_toggle = Gio.SimpleAction.new("edit-toggle", None)
        edit_toggle.connect("activate", self._on_edit_shortcut)
        self.add_action(edit_toggle)
        self._apply_edit_shortcut()
        self._apply_typewriter_shortcut()

        search = Gio.SimpleAction.new("search", None)
        search.connect("activate", self._on_search)
        self.add_action(search)
        self.get_application().set_accels_for_action("win.search", ["<Control><Shift>f"])

        tag_filter = Gio.SimpleAction.new("tag-filter", None)
        tag_filter.connect("activate", self._on_tag_filter)
        self.add_action(tag_filter)
        self.get_application().set_accels_for_action("win.tag-filter", ["<Control>t"])

        typewriter = Gio.SimpleAction.new("typewriter", None)
        typewriter.connect("activate", self._on_typewriter_action)
        self.add_action(typewriter)

        nav_back = Gio.SimpleAction.new("nav-back", None)
        nav_back.connect("activate", lambda *_: self._navigate_back())
        self.add_action(nav_back)
        self.get_application().set_accels_for_action("win.nav-back", ["<Alt>Left"])

        nav_fwd = Gio.SimpleAction.new("nav-forward", None)
        nav_fwd.connect("activate", lambda *_: self._navigate_forward())
        self.add_action(nav_fwd)
        self.get_application().set_accels_for_action("win.nav-forward", ["<Alt>Right"])

        self._export_pdf_action = Gio.SimpleAction.new("export-pdf", None)
        self._export_pdf_action.set_enabled(False)
        self._export_pdf_action.connect("activate", self._on_export_pdf)
        self.add_action(self._export_pdf_action)

    def _on_editor_save(self):
        if self._current_file and self._editing:
            self._save_edits(lambda: None)

    def _save_edits(self, then, overwrite=False):
        """Write the editor's text, then call `then`.

        `then` doesn't run if the save fails or the user cancels it, so
        whoever asked is left in the editor with their text intact.
        """
        try:
            self._note = save_note(self._current_file, self._editor.get_text(),
                                   self._note, overwrite)
        except NoteChanged:
            self._prompt_note_changed(then)
        except UnicodeEncodeError:
            self._save_failed(_("Some of the text can\u2019t be stored as {encoding}")
                              .format(encoding=self._note.encoding))
        except OSError as err:
            self._save_failed(err.strerror or str(err))
        else:
            self._tag_index.update_file(self._current_file)
            then()

    def _save_failed(self, reason):
        self._edit_btn.set_active(True)
        self.show_toast(
            _("Could not save \u201c{name}\u201d: {reason}").format(
                name=os.path.basename(self._current_file), reason=reason),
            "error", timeout=0,
        )

    def _prompt_note_changed(self, then):
        name = os.path.basename(self._current_file)
        gone = not os.path.exists(self._current_file)
        if gone:
            dialog = Adw.AlertDialog(
                heading=_("Note Deleted"),
                body=_("\u201c{name}\u201d was deleted while you were editing it.")
                .format(name=name),
            )
            dialog.add_response("cancel", _("Keep Editing"))
            dialog.add_response("overwrite", _("Save Again"))
        else:
            dialog = Adw.AlertDialog(
                heading=_("Note Changed"),
                body=_("\u201c{name}\u201d changed on disk while you were editing it.")
                .format(name=name),
            )
            dialog.add_response("cancel", _("Keep Editing"))
            dialog.add_response("reload", _("Use Version on Disk"))
            dialog.add_response("overwrite", _("Overwrite"))
            dialog.set_response_appearance("reload", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_response_appearance("overwrite", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_note_changed_response, then)
        dialog.present(self)

    def _on_note_changed_response(self, _dialog, response, then):
        if response == "overwrite":
            self._save_edits(then, overwrite=True)
        elif response == "reload":
            try:
                self._note = read_note(self._current_file)
            except OSError as err:
                self._save_failed(err.strerror or str(err))
                return
            self._editor.load_text(self._note.text)
            then()
        else:
            self._edit_btn.set_active(True)

    def _on_editor_escape(self):
        """Escape in the editor — same exit as the edit button, saving included."""
        if self._editing:
            self._edit_btn.set_active(False)

    def _on_find(self, *_args):
        focus = self.get_focus()
        in_list = focus is not None and focus.is_ancestor(self._list_toolbar)
        if not self._current_file or (in_list and self._list_stack.get_visible_child_name() == "documents"):
            self._reveal_lists()
            self._show_documents_list()
            self._doc_panel.focus_filter()
        elif self._editing:
            self._editor.toggle_search()
        else:
            self._viewer.toggle_search()

    # ---- Column layout ----------------------------------------------------

    @property
    def _note_only(self):
        return not self._list_split.get_show_sidebar()

    def _set_note_only(self, note_only):
        """Hide the sidebar and the list together, or bring both back."""
        self._layout_syncing = True
        try:
            if note_only:
                self._sidebar_before_note_only = self._split_view.get_show_sidebar()
                self._split_view.set_show_sidebar(False)
                self._list_split.set_show_sidebar(False)
            else:
                self._list_split.set_show_sidebar(True)
                # An overlay sidebar would cover the list it just brought back
                if not self._split_view.get_collapsed():
                    self._split_view.set_show_sidebar(self._sidebar_before_note_only)
        finally:
            self._layout_syncing = False

    def _reveal_lists(self):
        """Search, tags and the filter live in the list, so it must be on screen."""
        if self._note_only:
            self._set_note_only(False)

    def _on_lists_toggled(self, _btn):
        self._set_note_only(not self._note_only)

    def _dismiss_overlays(self):
        """A pick made in a folded column hands the room back to the note."""
        if self._split_view.get_collapsed():
            self._split_view.set_show_sidebar(False)
        if self._list_split.get_collapsed():
            self._list_split.set_show_sidebar(False)

    def _on_layout_changed(self, _split, _param):
        if self._editing and not self._layout_syncing:
            # Changed by hand mid-edit — leave it alone when edit mode ends
            self._sidebar_before_edit = None
        side_docked = (self._split_view.get_show_sidebar()
                       and not self._split_view.get_collapsed())
        list_docked = (self._list_split.get_show_sidebar()
                       and not self._list_split.get_collapsed())
        # Window buttons go on whichever header is leftmost
        self._list_header.set_show_start_title_buttons(not side_docked)
        self._content_header.set_show_start_title_buttons(not side_docked and not list_docked)
        self._list_sidebar_btn.set_visible(not side_docked)
        if self._note_only:
            self._lists_btn.set_icon_name("stenmark-sidebar-show-symbolic")
            self._lists_btn.set_tooltip_text(_("Show lists"))
        else:
            self._lists_btn.set_icon_name("stenmark-sidebar-hide-symbolic")
            self._lists_btn.set_tooltip_text(_("Show note only"))

    def _restore_sidebar_after_edit(self):
        if self._sidebar_before_edit is None:
            return
        self._sidebar_before_edit = None
        self._set_note_only(False)

    def _on_edit_toggled(self, btn):
        # Only a press that disagrees with the actual state means anything.
        # Everything else is the button being put right, which must not save.
        if btn.get_active() == self._editing:
            return
        if btn.get_active():
            self._enter_edit_mode()
        else:
            self._leave_edit_mode()

    def _enter_edit_mode(self):
        if not self._current_file:
            self._restore_sidebar_after_edit()
            self._edit_btn.set_active(False)
            return
        try:
            self._note = read_note(self._current_file)
        except OSError as err:
            self._edit_btn.set_active(False)
            self.show_toast(
                _("Could not open \u201c{name}\u201d: {reason}").format(
                    name=os.path.basename(self._current_file),
                    reason=err.strerror or str(err)),
                "error",
            )
            return
        text = self._note.text
        self._editor.load_text(text)
        if self._preview_btn.get_active():
            self._preview_viewer.render_text(text, self._current_file)

        # Land where the reader was, so editing picks up mid-document
        # instead of at line 1.
        pos = self._pending_edit_pos
        self._pending_edit_pos = None
        if pos and pos[0]:
            self._editor.goto_line(pos[0], pos[1], center=True)
        else:
            self._viewer.get_top_source_line(self._editor.goto_line)

        # Editing wants the width — the lists come back on the way out
        if self._settings.hide_sidebar_on_edit and not self._note_only:
            self._set_note_only(True)
            self._sidebar_before_edit = True

        self._stack.set_visible_child_name("edit")
        self._editing = True
        self._preview_btn.set_visible(True)
        # After the stack has actually swapped, or the WebView is not yet
        # mapped and cannot take focus
        GLib.idle_add(lambda: (self._editor.focus_editor(), GLib.SOURCE_REMOVE)[1])
        self._open_in_btn.set_sensitive(False)
        self._stop_watching()

    def _leave_edit_mode(self, then=None, save=True):
        """The one way out of edit mode, saving unless told not to.

        `then` runs once editing has really ended. A save can fail, or stop
        to ask about a newer version, so nothing may assume it happened
        before this returns.
        """
        def finish():
            self._close_editor()
            if then:
                then()

        if save:
            self._save_edits(finish)
        else:
            finish()

    def _close_editor(self):
        self._restore_sidebar_after_edit()
        # What's on disk, rather than the editor's text: a discard or an
        # unchanged note leaves the two different.
        try:
            note = read_note(self._current_file)
        except OSError:
            note = self._note
        self._note = None
        self._viewer.render_text(note.text, self._current_file)
        self._update_stats(note.text)
        self._update_toc(note.text)
        # ... and the other way round: show the reader the line being edited
        self._editor.get_top_line(self._viewer.scroll_to_line)
        self._stack.set_visible_child_name("view")
        self._editing = False
        self._edit_btn.set_active(False)
        self._preview_btn.set_visible(False)
        self._open_in_btn.set_sensitive(True)
        self._tag_index.update_file(self._current_file)
        self._start_watching()

    def _on_edit_requested(self, _viewer, line, word):
        """Double-click in the reader — edit this very spot."""
        if self._editing or not self._current_file:
            return
        self._pending_edit_pos = (line, word)
        self._edit_btn.set_active(True)

    def _on_edit_requested_preview(self, _viewer, line, word):
        """Double-click in the preview pane — move the caret there."""
        if self._editing and line:
            self._editor.goto_line(line, word, center=True)

    def _on_folder_selected(self, _sidebar, folder_path):
        self._doc_panel.show_folder(folder_path)
        self._show_documents_list()
        self._reveal_lists()
        if self._split_view.get_collapsed():
            self._split_view.set_show_sidebar(False)

    def _on_folder_navigated(self, _panel, _folder_path):
        self._update_list_header()

    def _on_typewriter_action(self, *_args):
        # The readout is inert outside edit mode; so is the shortcut, rather
        # than silently arming a mode you can't see the effect of.
        if not self._editing:
            return
        self._settings.set("editor_typewriter", not self._settings.editor_typewriter)

    def _update_typewriter_label(self):
        on = self._settings.editor_typewriter
        self._typewriter_btn.set_label(
            _("Typewriter = ON") if on else _("Typewriter = OFF")
        )
        # Insensitive in view mode: GTK dims it, which is exactly the "this is
        # information, not a control right now" the bar wants to say.
        self._typewriter_btn.set_sensitive(self._editing)
        self._typewriter_btn.set_cursor_from_name("pointer" if self._editing else None)
        if not self._editing:
            self._typewriter_btn.set_tooltip_text(None)
        else:
            accel = self._typewriter_accel_label()
            self._typewriter_btn.set_tooltip_text(
                _("Keep the current line centred ({accel})").format(accel=accel)
                if accel else _("Keep the current line centred")
            )

    # ---- List column -------------------------------------------------------

    def _show_documents_list(self):
        """Back from search or the tag filter to the folder's documents."""
        page = self._list_stack.get_visible_child_name()
        if page == "search":
            self._search_panel.clear()
        elif page == "tags":
            self._tag_panel.clear()
        if page != "documents":
            self._doc_panel.refresh()
        self._list_stack.set_visible_child_name("documents")
        self._update_list_header()

    def _on_list_back_clicked(self, _btn):
        if self._list_stack.get_visible_child_name() != "documents":
            self._show_documents_list()
        elif self._doc_panel.is_drilled_in:
            self._doc_panel.navigate_back()
            self._update_list_header()

    def _update_list_header(self):
        page = self._list_stack.get_visible_child_name()
        self._list_back_btn.set_visible(
            page != "documents" or self._doc_panel.is_drilled_in)
        if page == "search":
            self._list_title.set_title(_("Search"))
        elif page == "tags":
            self._list_title.set_title(_("Tags"))
        else:
            self._list_title.set_title(self._folder_label())

    def _folder_label(self):
        from stenmark.sidebar import Sidebar
        folder = self._doc_panel._current_folder
        if folder and folder.startswith("tag:"):
            return _("Tagged: {tag}").format(tag=folder[4:])
        if folder == Sidebar.ALL_DOCUMENTS:
            return _("All Documents")
        if folder == Sidebar.NO_FOLDER:
            return _("No Folder")
        if self._doc_panel.is_drilled_in:
            return os.path.basename(self._doc_panel._browsing_folder)
        return os.path.basename(folder) if folder else ""

    def _update_list_tint(self):
        """The sidebar's tint, carried more faintly into the list column."""
        if self._settings.get("tint_sidebar"):
            self._list_stack.add_css_class("list-column-tint")
        else:
            self._list_stack.remove_css_class("list-column-tint")

    def _show_default_folder(self):
        """List All Documents, as a fresh window or a new root starts out."""
        from stenmark.sidebar import Sidebar
        if self._settings.root_directory:
            self._sidebar.set_selection(Sidebar.ALL_DOCUMENTS)
            self._doc_panel.show_folder(Sidebar.ALL_DOCUMENTS)
        else:
            self._sidebar.set_selection(None)
            self._doc_panel.clear_selection()
        self._show_documents_list()

    def _on_file_created(self, _sidebar, path):
        if self._editing:
            self._leave_edit_mode(lambda: self._on_file_created(_sidebar, path))
            return
        self._load_file(path)
        self._edit_btn.set_active(True)

    def _on_file_selected(self, _panel, path):
        if self._editing:
            self._prompt_unsaved(lambda: self._load_file(path))
            return
        # Reset link navigation history when opening from the panel/search
        self._nav_history = [path]
        self._nav_index = 0
        self._load_file(path)
        self._dismiss_overlays()

    def _on_viewer_link(self, _viewer, path):
        if self._editing:
            self._prompt_unsaved(lambda: self._load_file(path))
            return
        self._load_file(path, push_history=True)

    def _navigate_back(self):
        if self._nav_index <= 0:
            return
        if self._editing:
            return
        self._nav_index -= 1
        self._load_file(self._nav_history[self._nav_index], push_history=False)

    def _navigate_forward(self):
        if self._nav_index >= len(self._nav_history) - 1:
            return
        if self._editing:
            return
        self._nav_index += 1
        self._load_file(self._nav_history[self._nav_index], push_history=False)

    def _sync_nav_state(self):
        self._viewer.set_nav_state(
            self._nav_index > 0,
            self._nav_index < len(self._nav_history) - 1,
        )

    def _on_mouse_button(self, gesture, _n_press, _x, _y):
        button = gesture.get_current_button()
        if button == 8:    # mouse back
            self._navigate_back()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        elif button == 9:  # mouse forward
            self._navigate_forward()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def open_file(self, path):
        """Open a file directly in view mode, the lists hidden."""
        self._set_note_only(True)
        self._load_file(path)
        # Show "Open root folder" in sidebar if file is outside the
        # persistent root (ceiling), not the session override.
        # realpath("") is the working directory, so an unset root would put
        # every file "outside" it.
        ceiling = os.path.realpath(os.path.expanduser(self._root_ceiling)) if self._root_ceiling else ""
        file_dir = os.path.realpath(os.path.dirname(path))
        if ceiling and file_dir != ceiling and not file_dir.startswith(ceiling + os.sep):
            self._sidebar.set_outside_root(True)

    def _load_file(self, path, push_history=False):
        if push_history:
            # Truncate forward history and append
            self._nav_history = self._nav_history[:self._nav_index + 1]
            self._nav_history.append(path)
            self._nav_index = len(self._nav_history) - 1
        self._current_file = path
        self._doc_panel.select_file(path)
        self._edit_btn.set_sensitive(True)
        self._copy_rich_btn.set_visible(True)
        self._open_in_btn.set_visible(True)
        self._export_pdf_action.set_enabled(True)
        self._toc_btn.set_visible(True)
        self._tags_btn.set_visible(True)
        self._show_doc_title(path)
        self._viewer.load_file(path)
        self._stack.set_visible_child_name("view")
        self._start_watching()
        try:
            text = read_note(path).text
            self._update_stats(text)
            self._update_toc(text)
        except OSError:
            pass
        self._sync_nav_state()

    def _show_doc_title(self, path):
        """Name the open note in the header bar and the window title; None for no note."""
        if path is None:
            self._title_widget.set_title(APP_NAME)
            self.set_title(APP_NAME)
            return
        name = os.path.basename(path)
        self._title_widget.set_title(name)
        self.set_title(_("{document} — Stenmark").format(document=name))

    def _prompt_unsaved(self, then):
        """Leave edit mode and call `then`, asking first if there's anything to lose."""
        if self._editor.get_text() == self._note.text:
            self._leave_edit_mode(then)
            return
        dialog = Adw.AlertDialog(
            heading=_("Unsaved Changes"),
            body=_("You have unsaved changes. What would you like to do?"),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("discard", _("Discard"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        dialog.connect("response", self._on_unsaved_response, then)
        dialog.present(self)

    def _on_unsaved_response(self, _dialog, response, then):
        if response == "cancel":
            return
        self._leave_edit_mode(then, save=response == "save")

    def _start_watching(self):
        self._stop_watching()
        if not self._settings.file_watching or not self._current_file:
            return
        try:
            from stenmark.file_watcher import FileWatcher
            self._watcher = FileWatcher(self._current_file, self._on_file_changed)
        except Exception:  # nosec B110
            pass

    def _stop_watching(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def _on_file_changed(self):
        if self._editing or not self._current_file:
            return
        self._viewer.reload_in_place(self._current_file)
        try:
            text = read_note(self._current_file).text
        except OSError:
            return
        self._update_stats(text)
        self._update_toc(text)

    def _on_file_trashed(self, _panel, path):
        self._tag_index.remove_file(path)
        if self._current_file == path:
            self._stop_watching()
            self._current_file = None
            self._note = None
            self._editing = False
            self._restore_sidebar_after_edit()
            self._edit_btn.set_active(False)
            self._edit_btn.set_sensitive(False)
            self._preview_btn.set_visible(False)
            self._open_in_btn.set_sensitive(True)
            self._copy_rich_btn.set_visible(False)
            self._open_in_btn.set_visible(False)
            self._export_pdf_action.set_enabled(False)
            self._toc_btn.set_visible(False)
            self._tags_btn.set_visible(False)
            self._show_doc_title(None)
            self._status_bar.set_visible(False)
            self._doc_panel.select_file(None)
            self._stack.set_visible_child_name("welcome")
        self._sidebar.refresh()

    def _on_file_renamed(self, _panel, old_path, new_path):
        self._tag_index.remove_file(old_path)
        self._tag_index.update_file(new_path)
        self._path_moved(old_path, new_path)
        self._sidebar.refresh()

    def _on_folder_renamed(self, _source, old_path, new_path):
        self._path_moved(old_path, new_path)
        self._tag_index.rebuild()
        self._doc_panel.folder_renamed(old_path, new_path)
        self._doc_panel.refresh()
        self._sidebar.refresh()

    def _path_moved(self, old_path, new_path):
        self._settings.move_pins(old_path, new_path)
        self._nav_history = [moved_path(p, old_path, new_path) for p in self._nav_history]
        if not self._current_file:
            return
        moved = moved_path(self._current_file, old_path, new_path)
        if moved != self._current_file:
            self._current_file = moved
            self._viewer.follow_rename(moved)
            self._doc_panel.select_file(moved)
            self._show_doc_title(moved)
            if not self._editing:
                self._start_watching()

    def _on_settings_changed(self, _mgr, key):
        if key == "root_directory":
            # Update ceiling if this was a persistent change (not an override)
            persisted = self._settings._data.get("root_directory")
            if persisted and "root_directory" not in self._settings._overrides:
                self._root_ceiling = persisted
            self._tag_index.set_root(self._settings.root_directory)
            self._rebuild_root_model()
            # A new root starts fresh, on its own All Documents: both panes
            # still hold a selection made against the tree we just left.
            self._sidebar.refresh()
            self._show_default_folder()
            self._welcome.refresh()
        elif key in ("font_family", "font_size", "viewer_theme"):
            self._viewer.update_style()
            self._preview_viewer.update_style()
        elif key in ("editor_font_family", "editor_font_size",
                     "editor_theme", "editor_line_numbers", "editor_line_wrap",
                     "editor_typewriter"):
            if key == "editor_typewriter":
                # Preferences or the shortcut may have moved it.
                self._update_typewriter_label()
            self._editor.update_style()
        elif key == "edit_shortcut":
            self._apply_edit_shortcut()
        elif key == "typewriter_shortcut":
            self._apply_typewriter_shortcut()
        elif key == "file_watching":
            if self._settings.file_watching:
                self._start_watching()
            else:
                self._stop_watching()
        elif key == "show_sidebar_tags":
            self._sidebar.refresh()
        elif key == "tint_sidebar":
            self._sidebar.update_tint()
            self._update_list_tint()
        elif key == "double_click_to_edit":
            enabled = self._settings.double_click_to_edit
            self._viewer.set_edit_on_dblclick(enabled)
            self._preview_viewer.set_edit_on_dblclick(enabled)

    def _on_preview_toggled(self, btn):
        active = btn.get_active()
        self._settings.set("preview_enabled", active)
        self._preview_viewer.set_visible(active)
        if active:
            text = self._editor.get_text()
            self._preview_viewer.render_text(text, self._current_file)

    def _on_preview_text_changed(self, text):
        self._update_stats(text)
        self._update_toc(text)
        if not self._preview_btn.get_active():
            return
        if self._preview_timeout_id:
            GLib.source_remove(self._preview_timeout_id)
        self._preview_timeout_id = GLib.timeout_add(
            150, self._do_preview_update, text
        )

    def _do_preview_update(self, text):
        self._preview_timeout_id = None
        self._preview_viewer.render_text(text, self._current_file)
        return GLib.SOURCE_REMOVE

    def _on_editor_scroll(self, line):
        if self._stack.get_visible_child_name() == "edit" and self._preview_btn.get_active():
            self._preview_viewer.scroll_to_line(line)

    def _on_export_pdf(self, *_args):
        if self._editing:
            self._preview_viewer.print_pdf(self)
        else:
            self._viewer.print_pdf(self)

    def _on_open_in(self, btn):
        if not self._current_file:
            return

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
        popover.set_parent(btn)
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
            row_btn = Gtk.Button()
            row_btn.add_css_class("flat")
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
            row_btn.set_child(row_box)
            row_btn.connect("clicked", self._launch_file_with_app, app, popover)
            box.append(row_btn)

        popover.set_child(box)
        popover.popup()

    def _launch_file_with_app(self, _btn, app, popover):
        popover.popdown()
        if self._current_file:
            uri = Gio.File.new_for_path(self._current_file).get_uri()
            try:
                app.launch_uris([uri], None)
            except Exception:  # nosec B110
                pass

    def _on_copy_rich_text(self, _btn):
        if self._editing:
            text = self._editor.get_text()
        elif self._current_file:
            try:
                text = read_note(self._current_file).text
            except OSError:
                return
        else:
            return

        body = self._renderer.render(text)
        html = f"<html><body>{body}</body></html>"

        providers = [
            Gdk.ContentProvider.new_for_bytes(
                "text/html", GLib.Bytes.new(html.encode("utf-8"))
            ),
            Gdk.ContentProvider.new_for_value(text),
        ]
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set_content(Gdk.ContentProvider.new_union(providers))
        self.show_toast(_("Copied as rich text"), "success")

    def _update_stats(self, text):
        words = len(text.split())
        minutes = max(1, round(words / 200))
        self._word_count_label.set_label(
            ngettext("{n} word", "{n} words", words).format(n=words)
        )
        self._reading_time_label.set_label(
            _("{n} min read").format(n=minutes)
        )
        self._update_typewriter_label()
        self._status_bar.set_visible(True)

    def _apply_typewriter_shortcut(self):
        # Validated first: the row is free text, and handing GTK something it
        # can't parse earns a console critical and installs nothing anyway.
        shortcut = self._settings.typewriter_shortcut
        valid = bool(shortcut) and Gtk.accelerator_parse(shortcut)[0]
        self.get_application().set_accels_for_action(
            "win.typewriter", [shortcut] if valid else []
        )
        # The readout names the key, so it has to be renamed with it.
        self._update_typewriter_label()

    def _typewriter_accel_label(self):
        """The configured shortcut as a user would write it, or "" if unset."""
        shortcut = self._settings.typewriter_shortcut
        if not shortcut:
            return ""
        ok, keyval, mods = Gtk.accelerator_parse(shortcut)
        return Gtk.accelerator_get_label(keyval, mods) if ok else ""

    def _apply_edit_shortcut(self):
        shortcut = self._settings.edit_shortcut
        if shortcut:
            self.get_application().set_accels_for_action(
                "win.edit-toggle", [shortcut]
            )
        else:
            self.get_application().set_accels_for_action("win.edit-toggle", [])

    def _on_edit_shortcut(self, *_args):
        if self._current_file:
            self._edit_btn.set_active(not self._edit_btn.get_active())

    def _update_toc(self, text):
        self._toc_headings = self._renderer.headings(text)
        while True:
            row = self._toc_list.get_row_at_index(0)
            if row is None:
                break
            self._toc_list.remove(row)
        for level, title, _line in self._toc_headings:
            label = Gtk.Label(
                label=title,
                xalign=0,
                ellipsize=3,  # Pango.EllipsizeMode.END
            )
            label.set_margin_start((level - 1) * 16)
            if level == 1:
                label.add_css_class("heading")
            elif level >= 3:
                label.add_css_class("dim-label")
            self._toc_list.append(label)

    def _on_toc_row_activated(self, _listbox, row):
        self._toc_popover.popdown()
        idx = row.get_index()
        if idx >= len(self._toc_headings):
            return
        _level, _title, line_num = self._toc_headings[idx]
        if self._editing:
            self._editor._js(f"scrollToLine({line_num})")
        else:
            self._viewer.scroll_to_line(line_num)

    def show_toast(self, message, kind="info", timeout=3):
        _icons = {
            "error": ("dialog-error-symbolic", "toast-error-icon"),
            "success": ("emblem-ok-symbolic", "toast-success-icon"),
            "warning": ("dialog-warning-symbolic", "toast-warning-icon"),
        }
        toast = Adw.Toast(timeout=timeout)
        if kind in _icons:
            icon_name, css_class = _icons[kind]
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                          spacing=8, valign=Gtk.Align.CENTER)
            box.append(Gtk.Image(icon_name=icon_name, pixel_size=16,
                                 css_classes=[css_class]))
            box.append(Gtk.Label(label=message))
            toast.set_custom_title(box)
        else:
            toast.set_title(message)
        self._toast_overlay.add_toast(toast)

    # ---- Tag editor popover -----------------------------------------------

    def _on_tags_clicked(self, btn):
        if not self._current_file:
            return

        tags = list(read_tags(self._current_file))

        popover = Gtk.Popover()
        popover.set_parent(btn)
        popover.set_has_arrow(True)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_start=8,
            margin_end=8,
            margin_top=8,
            margin_bottom=8,
        )
        outer.set_size_request(260, -1)

        # Current tags as removable chips
        chips_box = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=10,
            homogeneous=False,
        )
        chips_box.set_row_spacing(4)
        chips_box.set_column_spacing(4)

        def rebuild_chips():
            while True:
                child = chips_box.get_first_child()
                if child is None:
                    break
                chips_box.remove(child)
            for tag in tags:
                chip_box = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL,
                    spacing=4,
                    css_classes=["tag-chip"],
                )
                chip_box.append(Gtk.Label(label=tag, css_classes=["caption"]))
                remove_btn = Gtk.Button(
                    icon_name="stenmark-close-symbolic",
                    css_classes=["flat", "circular"],
                    valign=Gtk.Align.CENTER,
                )
                remove_btn.set_size_request(16, 16)
                remove_btn.connect("clicked", on_remove_tag, tag)
                chip_box.append(remove_btn)
                chips_box.append(chip_box)

        def on_remove_tag(_btn, tag):
            if tag in tags:
                tags.remove(tag)
                update_tags(self._current_file, tags)
                self._tag_index.update_file(self._current_file)
                self._sidebar.refresh_tags()
                rebuild_chips()

        rebuild_chips()
        outer.append(chips_box)

        # Entry for adding new tags with autocomplete
        entry = Gtk.Entry(
            placeholder_text=_("Add tag\u2026"),
            hexpand=True,
        )

        # Autocomplete via EntryCompletion
        completion = Gtk.EntryCompletion()
        store = Gtk.ListStore(str)
        for t in self._tag_index.all_tags():
            store.append([t])
        completion.set_model(store)
        completion.set_text_column(0)
        completion.set_minimum_key_length(1)
        completion.set_popup_completion(True)
        entry.set_completion(completion)

        def on_entry_activate(_entry):
            new_tag = _entry.get_text().strip().lower()
            if not new_tag or new_tag in tags:
                _entry.set_text("")
                return
            tags.append(new_tag)
            tags.sort()
            update_tags(self._current_file, tags)
            self._tag_index.update_file(self._current_file)
            self._sidebar.refresh_tags()
            # Update autocomplete model
            if not any(row[0] == new_tag for row in store):
                store.append([new_tag])
            rebuild_chips()
            _entry.set_text("")

        entry.connect("activate", on_entry_activate)
        outer.append(entry)

        popover.set_child(outer)
        popover.popup()

    def _on_close_request(self, _win):
        if self.get_visible_dialog():
            return True
        if self._editing:
            # On an idle callback: GTK ignores close() during close-request
            self._prompt_unsaved(lambda: GLib.idle_add(self.close))
            return True
        if self._settings.get("remember_last_folder") and not getattr(self._settings, "cli_root", False):
            self._settings.set("last_root_folder", self._settings.root_directory)
        return False

    def _on_set_root_from_welcome(self):
        """Open preferences dialog so the user can set a root directory."""
        from stenmark.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self._settings)
        # Presented without a parent it gets its own window, so no dimming
        # backdrop lies over the editor while a theme is being chosen.
        dialog.present(None)

    def _on_new_file_from_welcome(self):
        """Trigger the sidebar's new-file dialog."""
        self._sidebar.activate_action("sidebar.new-file", None)

    def _on_tag_filter(self, *_args):
        """Switch to the tag filter pane."""
        self._open_tag_panel()

    def _open_tag_panel(self, preselect_tag=None):
        """Show the tag filter in the list column, optionally pre-selecting a tag."""
        self._reveal_lists()
        if preselect_tag:
            self._tag_panel.select_tag(preselect_tag)
        else:
            self._tag_panel.show_tags()
        self._list_stack.set_visible_child_name("tags")
        self._update_list_header()
        self._tag_panel.focus_entry()

    def _on_search(self, *_args):
        """Show full-text search in the list column."""
        self._reveal_lists()
        # Scope search to the currently selected folder
        folder = self._doc_panel._current_folder
        if folder:
            self._search_panel.set_folder(folder)
        self._list_stack.set_visible_child_name("search")
        self._update_list_header()
        self._search_panel.focus_search()

    def _on_preferences(self, *_args):
        from stenmark.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self._settings)
        # Presented without a parent it gets its own window, so no dimming
        # backdrop lies over the editor while a theme is being chosen.
        dialog.present(None)

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon="de.singular.stenmark-symbolic",
            version=VERSION,
            developer_name="Kreuder <mk@singular.de>",
            website="https://github.com/mkay/stenmark",
            license_type=Gtk.License.GPL_3_0_ONLY,
        )
        # Left untranslated in a catalogue, this stays the msgid — which means
        # nobody has claimed the translation, so there is no one to credit.
        credits = _("translator-credits")
        if credits != "translator-credits":
            about.set_translator_credits(credits)

        # translator-credits above only ever shows the language being read, so
        # a translator is credited to the people already reading their own
        # work. This section is the permanent roll, visible in every locale.
        # German is not listed: that is the developer, credited above.
        about.add_credit_section(_("Translators"), [
            "derVedro (Русский)",
        ])

        # The durable home for the invitation: the language row in Preferences
        # carries it too, but only someone who goes looking for it sees it.
        from stenmark.i18n import TRANSLATE_URL
        about.add_link(_("Help Translate Stenmark"), TRANSLATE_URL)

        # The same asks the Support dialog makes, as plain links: About is
        # where someone lands when they go looking for the project, and the
        # dialog is only reachable from the menu.
        from stenmark.support_dialog import KOFI_URL, LIKE_URL
        about.add_link(_("Give Stenmark a Like"), LIKE_URL)
        about.add_link(_("Support Stenmark on Ko-fi"), KOFI_URL)

        # Gives About its own "What's New" section, so the notes stay reachable
        # after the one-off dialog has been dismissed.
        from stenmark.whats_new_dialog import release_notes_markup
        notes = release_notes_markup()
        if notes:
            about.set_release_notes(notes)
            about.set_release_notes_version(VERSION)

        about.present(self)

    # ---- Open root folder (sidebar, file outside root) --------------------

    def _on_open_root_requested(self, _sidebar):
        ceiling = os.path.expanduser(self._root_ceiling)
        self._settings.set_override("root_directory", ceiling)
        self._sidebar_before_note_only = True
        self._set_note_only(False)

    # ---- Root folder navigation (sidebar header) -------------------------

    def _on_sidebar_changed(self, _sidebar):
        # Folders may have been created, renamed or deleted
        self._rebuild_root_model()
        self._doc_panel.refresh()

    def _root_row_factory(self, indent):
        """Factory for the selector's rows — folder icon plus name.

        The popup rows (indent=True) show nesting as an indent; the button
        (indent=False) shows the plain folder name.
        """
        factory = Gtk.SignalListItemFactory()

        def on_setup(_f, list_item):
            # The button sits directly above the sidebar rows, which pair a
            # spacing=8 box with an untrimmed icon — 8px plus the ~1px of dead
            # space inside its viewBox. Our icon is trimmed flush, so it needs
            # the wider spacing to line up with them. The popup stands alone
            # and reads better tight.
            box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=4 if indent else 9,
            )
            box.append(Gtk.Image(icon_name="stenmark-folder-bold-symbolic"))
            box.append(Gtk.Label(xalign=0, hexpand=True, ellipsize=3))  # END
            if indent:
                box.append(Gtk.Image(icon_name="object-select-symbolic"))
            list_item.set_child(box)

        def on_bind(_f, list_item):
            item = list_item.get_item()
            box = list_item.get_child()
            icon = box.get_first_child()
            # On the button, nudge right so the icon lines up with the
            # sidebar rows below; in the popup, indent one step per level.
            icon.set_margin_start(item.depth * 16 if indent else 6)
            label = icon.get_next_sibling()
            label.set_label(item.name)
            if indent:
                # GtkListView recycles rows, so :nth-child CSS would stripe by
                # widget order and smear while scrolling. Bind carries the real
                # model position, and every row clears the class it inherited
                # from whatever item sat here before.
                position = list_item.get_position()
                if (position != Gtk.INVALID_LIST_POSITION
                        and position % 2 == 1):
                    box.add_css_class("root-row-alt")
                else:
                    box.remove_css_class("root-row-alt")
                list_item._binding = item.bind_property(
                    "selected", box.get_last_child(), "visible",
                    GObject.BindingFlags.SYNC_CREATE,
                )

        def on_unbind(_f, list_item):
            # Rows are recycled; drop the binding or it keeps tracking the
            # item that used to live here.
            binding = getattr(list_item, "_binding", None)
            if binding is not None:
                binding.unbind()
                list_item._binding = None

        factory.connect("setup", on_setup)
        factory.connect("bind", on_bind)
        factory.connect("unbind", on_unbind)
        return factory

    def _rebuild_root_model(self):
        """Fill the selector with the ceiling folder and every folder below it."""
        ceiling = os.path.expanduser(self._root_ceiling)

        if ROOT_DRILLDOWN:
            # The drill-down reads one level at a time, so it only needs the
            # ceiling; it walks the rest itself when a page is pushed.
            if ceiling != self._root_ceiling_shown:
                self._root_ceiling_shown = ceiling
                self._root_dropdown.set_ceiling(ceiling)
            else:
                self._root_dropdown.refresh()
            self._update_root_label()
            return

        paths = [ceiling] + _collect_tree(ceiling)

        # Switching root doesn't move any folder, so the list is usually
        # identical and only the selection has changed. Splicing regardless
        # would drop and rebuild every row widget — and since this can run
        # from the dropdown's own notify::selected handler, GTK would tear
        # down widgets it is still using and the popup would stop opening.
        if paths == self._root_paths:
            self._update_root_label()
            return
        self._root_paths = paths

        base = os.path.basename(ceiling.rstrip(os.sep)) or ceiling
        items = [RootFolder(name=base, depth=0)]
        for path in self._root_paths[1:]:
            rel = os.path.relpath(path, ceiling)
            items.append(RootFolder(
                name=os.path.basename(path),
                depth=rel.count(os.sep) + 1,
            ))

        self._root_syncing = True
        self._root_model.splice(0, self._root_model.get_n_items(), items)
        self._root_syncing = False
        self._update_root_label()

    def _update_root_label(self):
        """Point the selector at whatever the current root directory is."""
        root = self._settings.root_directory
        current = os.path.normpath(root) if root else ""

        if ROOT_DRILLDOWN:
            self._root_dropdown.set_current(current)
            return

        match = -1
        for i, path in enumerate(self._root_paths):
            if os.path.normpath(path) == current:
                match = i
                break

        for i in range(self._root_model.get_n_items()):
            self._root_model.get_item(i).props.selected = (i == match)

        self._root_syncing = True
        # No match means the root sits outside the tree we listed
        self._root_dropdown.set_selected(
            match if match >= 0 else Gtk.INVALID_LIST_POSITION
        )
        self._root_syncing = False

    def _on_root_selected(self, dropdown, _pspec):
        if self._root_syncing:
            return
        index = dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= len(self._root_paths):
            return
        # Applying the root change refreshes the sidebar, which can rebuild
        # this dropdown's model. Doing that here would mutate the widget
        # while it is still emitting notify::selected, so let it finish first.
        GLib.idle_add(self._apply_root_change, self._root_paths[index])

    def _on_root_folder_selected(self, _selector, path):
        # Same deferral as the dropdown path: applying the root refreshes the
        # sidebar, which rebuilds the selector we are being called from.
        GLib.idle_add(self._apply_root_change, path)

    def _apply_root_change(self, path):
        self._settings.set_override("root_directory", path)
        return GLib.SOURCE_REMOVE
