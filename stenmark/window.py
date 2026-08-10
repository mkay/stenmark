# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import os
import re

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Gio

from stenmark import APP_NAME, VERSION
from stenmark.i18n import _, ngettext
from stenmark.sidebar import Sidebar
from stenmark.document_panel import DocumentPanel
from stenmark.viewer import MarkdownViewer
from stenmark.editor import MarkdownEditor
from stenmark.welcome import WelcomeView
from stenmark.search_panel import SearchPanel
from stenmark.tag_index import TagIndex
from stenmark.tag_panel import TagPanel
from stenmark.frontmatter import read_tags, update_tags


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
        self._sidebar_before_edit = None

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
        self.connect("close-request", self._on_close_request)

        if open_file:
            self.open_file(open_file)

    def _build_ui(self):
        # === Sidebar ToolbarView ===
        sidebar_header = Adw.HeaderBar(show_end_title_buttons=False)

        self._root_popover = Gtk.Popover(position=Gtk.PositionType.BOTTOM)
        self._root_popover.set_has_arrow(True)

        self._root_label = Gtk.Label(
            label=os.path.basename(self._settings.root_directory),
            ellipsize=3,  # Pango.EllipsizeMode.END
            css_classes=["heading"],
        )
        self._root_btn = Gtk.MenuButton(
            css_classes=["flat"],
            popover=self._root_popover,
            child=self._root_label,
            direction=Gtk.ArrowType.NONE,
        )
        self._root_btn.connect("notify::active", self._on_root_btn_toggled)
        sidebar_header.set_title_widget(self._root_btn)

        # The "ceiling" is the configured root from settings (ignoring session overrides)
        self._root_ceiling = self._settings._data.get("root_directory", self._settings.get("root_directory"))

        self._sidebar = Sidebar(self._settings, tag_index=self._tag_index)

        sidebar_toolbar = Adw.ToolbarView()
        sidebar_toolbar.add_css_class("app-sidebar")
        sidebar_toolbar.add_top_bar(sidebar_header)
        sidebar_toolbar.set_content(self._sidebar)

        # === Content ToolbarView ===
        self._content_header = Adw.HeaderBar(show_start_title_buttons=False)

        # Back button (start, leftmost)
        self._back_btn = Gtk.Button(
            icon_name="stenmark-go-previous-symbolic",
            tooltip_text=_("Back"),
            visible=False,
        )
        self._back_btn.connect("clicked", self._on_back_clicked)
        self._content_header.pack_start(self._back_btn)

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
            icon_name="stenmark-preview-symbolic" if preview_on else "stenmark-preview-off-symbolic",
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

        # Sidebar toggle (left of menu button)
        self._sidebar_btn = Gtk.Button(
            icon_name="stenmark-sidebar-hide-symbolic",
            tooltip_text=_("Toggle sidebar"),
        )
        self._sidebar_btn.set_focus_on_click(False)
        self._content_header.pack_end(self._sidebar_btn)

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
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._welcome = WelcomeView(
            settings=self._settings,
            on_set_root=self._on_set_root_from_welcome,
            on_new_file=self._on_new_file_from_welcome,
        )
        self._stack.add_named(self._welcome, "welcome")

        self._doc_panel = DocumentPanel(self._settings, tag_index=self._tag_index)
        self._stack.add_named(self._doc_panel, "documents")

        self._search_panel = SearchPanel(self._settings)
        self._stack.add_named(self._search_panel, "search")

        self._tag_panel = TagPanel(self._settings, self._tag_index)
        self._stack.add_named(self._tag_panel, "tags")

        self._viewer = MarkdownViewer(self._settings)
        self._stack.add_named(self._viewer, "view")

        self._editor = MarkdownEditor(self._settings)
        self._preview_viewer = MarkdownViewer(self._settings)
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

        content_toolbar = Adw.ToolbarView()
        content_toolbar.add_top_bar(self._content_header)
        content_toolbar.add_bottom_bar(self._status_bar)
        content_toolbar.set_content(self._stack)

        # === Split View ===
        self._split_view = Adw.OverlaySplitView()
        self._split_view.set_show_sidebar(True)
        self._split_view.set_sidebar(sidebar_toolbar)
        self._split_view.set_content(content_toolbar)

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
        self._sidebar_btn.connect("clicked", self._on_sidebar_toggled)
        self._split_view.connect("notify::show-sidebar", self._on_split_sidebar_changed)
        self._edit_btn.connect("toggled", self._on_edit_toggled)
        self._sidebar.connect("folder-selected", self._on_folder_selected)
        self._sidebar.connect("changed", lambda _s: self._doc_panel.refresh())
        self._sidebar.connect("file-created", self._on_file_created)
        self._sidebar.connect("search-requested", lambda _s: self._on_search(None, None))
        self._sidebar.connect("tag-filter-requested", lambda _s: self._on_tag_filter(None, None))
        self._sidebar.connect("open-root-requested", self._on_open_root_requested)
        self._doc_panel.connect("file-selected", self._on_file_selected)
        self._doc_panel.connect("file-trashed", self._on_file_trashed)
        self._doc_panel.connect("file-renamed", self._on_file_renamed)
        self._doc_panel.connect("folder-navigated", self._on_folder_navigated)
        self._doc_panel.connect("tag-clicked", lambda _p, tag: self._open_tag_panel(tag))
        self._settings.connect("changed", self._on_settings_changed)
        self._editor.set_save_callback(self._on_editor_save)
        self._editor.set_preview_callback(self._on_preview_text_changed)
        self._editor.set_scroll_callback(self._on_editor_scroll)
        self._editor.set_escape_callback(self._on_editor_escape)
        self._search_panel.connect("file-selected", self._on_file_selected)
        self._search_panel.connect("close-requested", lambda _p: self._on_back_clicked(None))
        self._search_panel.connect("tag-filter-requested", lambda _p: self._open_tag_panel())
        self._tag_panel.connect("file-selected", self._on_file_selected)
        self._tag_panel.connect("close-requested", lambda _p: self._on_back_clicked(None))
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

        search = Gio.SimpleAction.new("search", None)
        search.connect("activate", self._on_search)
        self.add_action(search)
        self.get_application().set_accels_for_action("win.search", ["<Control><Shift>f"])

        tag_filter = Gio.SimpleAction.new("tag-filter", None)
        tag_filter.connect("activate", self._on_tag_filter)
        self.add_action(tag_filter)
        self.get_application().set_accels_for_action("win.tag-filter", ["<Control>t"])

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
        if not self._current_file or not self._editing:
            return
        text = self._editor.get_text()
        try:
            with open(self._current_file, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass
        self._tag_index.update_file(self._current_file)

    def _on_editor_escape(self):
        """Escape in the editor — same exit as the edit button, saving included."""
        if self._editing:
            self._edit_btn.set_active(False)

    def _on_find(self, *_args):
        page = self._stack.get_visible_child_name()
        if page == "documents":
            self._doc_panel.toggle_filter()
        elif self._editing:
            self._editor.toggle_search()
        else:
            self._viewer.toggle_search()

    def _on_sidebar_toggled(self, _btn):
        self._split_view.set_show_sidebar(not self._split_view.get_show_sidebar())

    def _on_split_sidebar_changed(self, split_view, _param):
        if self._editing:
            # Changed by hand mid-edit — leave it alone when edit mode ends
            self._sidebar_before_edit = None
        showing = split_view.get_show_sidebar()
        if showing:
            self._sidebar_btn.set_icon_name("stenmark-sidebar-hide-symbolic")
        else:
            self._sidebar_btn.set_icon_name("stenmark-sidebar-show-symbolic")
        self._content_header.set_show_start_title_buttons(not showing)

    def _restore_sidebar_after_edit(self):
        if self._sidebar_before_edit is None:
            return
        show = self._sidebar_before_edit
        self._sidebar_before_edit = None
        self._split_view.set_show_sidebar(show)

    def _on_edit_toggled(self, btn):
        if not self._current_file:
            self._restore_sidebar_after_edit()
            btn.set_active(False)
            return

        if btn.get_active():
            # Enter edit mode
            try:
                with open(self._current_file, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                btn.set_active(False)
                return
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

            # Editing wants the width — the sidebar comes back on the way out
            if (self._settings.hide_sidebar_on_edit
                    and self._split_view.get_show_sidebar()):
                self._sidebar_before_edit = True
                self._split_view.set_show_sidebar(False)

            self._stack.set_visible_child_name("edit")
            self._editing = True
            self._preview_btn.set_visible(True)
            # After the stack has actually swapped, or the WebView is not yet
            # mapped and cannot take focus
            GLib.idle_add(lambda: (self._editor.focus_editor(), GLib.SOURCE_REMOVE)[1])
            self._open_in_btn.set_sensitive(False)
            self._stop_watching()
        else:
            # Exit edit mode — save and re-render
            self._restore_sidebar_after_edit()
            text = self._editor.get_text()
            try:
                with open(self._current_file, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
            self._viewer.render_text(text, self._current_file)
            # ... and the other way round: show the reader the line being edited
            self._editor.get_top_line(self._viewer.scroll_to_line)
            self._stack.set_visible_child_name("view")
            self._editing = False
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
        if self._editing:
            # Save first, then show documents
            text = self._editor.get_text()
            try:
                with open(self._current_file, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
            self._editing = False
            self._edit_btn.set_active(False)
            self._preview_btn.set_visible(False)

        from stenmark.sidebar import Sidebar
        if folder_path.startswith("tag:"):
            self._title_widget.set_subtitle(
                _("Tagged: {tag}").format(tag=folder_path[4:]))
        elif folder_path == Sidebar.ALL_DOCUMENTS:
            self._title_widget.set_subtitle(_("All Documents"))
        elif folder_path == Sidebar.NO_FOLDER:
            self._title_widget.set_subtitle(_("No Folder"))
        else:
            self._title_widget.set_subtitle(os.path.basename(folder_path))

        self._edit_btn.set_sensitive(False)
        self._copy_rich_btn.set_visible(False)
        self._open_in_btn.set_visible(False)
        self._export_pdf_action.set_enabled(False)
        self._toc_btn.set_visible(False)
        self._tags_btn.set_visible(False)
        self._status_bar.set_visible(False)
        self._doc_panel.show_folder(folder_path)
        self._stack.set_visible_child_name("documents")
        self._update_back_btn()

    def _on_folder_navigated(self, _panel, folder_path):
        self._title_widget.set_subtitle(os.path.basename(folder_path))
        self._update_back_btn()

    def _update_back_btn(self):
        page = self._stack.get_visible_child_name()
        if page in ("view", "edit", "search", "tags"):
            self._back_btn.set_visible(True)
        elif page == "documents" and self._doc_panel.is_drilled_in:
            self._back_btn.set_visible(True)
        else:
            self._back_btn.set_visible(False)

    def _on_back_clicked(self, _btn):
        page = self._stack.get_visible_child_name()
        if page in ("view", "edit"):
            # Exit document view — save if editing
            if self._editing:
                text = self._editor.get_text()
                try:
                    with open(self._current_file, "w", encoding="utf-8") as f:
                        f.write(text)
                except OSError:
                    pass
                self._editing = False
                self._edit_btn.set_active(False)
                self._preview_btn.set_visible(False)
            self._stop_watching()
            self._current_file = None
            self._edit_btn.set_sensitive(False)
            self._copy_rich_btn.set_visible(False)
            self._open_in_btn.set_visible(False)
            self._export_pdf_action.set_enabled(False)
            self._toc_btn.set_visible(False)
            self._tags_btn.set_visible(False)
            self._status_bar.set_visible(False)
            self._sidebar.set_outside_root(False)
            self._doc_panel.refresh()
            self._stack.set_visible_child_name("documents")
            self._restore_folder_subtitle()
        elif page == "search":
            self._search_panel.clear()
            self._doc_panel.refresh()
            self._stack.set_visible_child_name("documents")
            self._restore_folder_subtitle()
        elif page == "tags":
            self._tag_panel.clear()
            self._doc_panel.refresh()
            self._stack.set_visible_child_name("documents")
            self._restore_folder_subtitle()
        elif page == "documents" and self._doc_panel.is_drilled_in:
            self._doc_panel.navigate_back()
        self._update_back_btn()

    def _restore_folder_subtitle(self):
        from stenmark.sidebar import Sidebar
        folder = self._doc_panel._current_folder
        if folder and folder.startswith("tag:"):
            self._title_widget.set_subtitle(
                _("Tagged: {tag}").format(tag=folder[4:]))
        elif folder == Sidebar.ALL_DOCUMENTS:
            self._title_widget.set_subtitle(_("All Documents"))
        elif folder == Sidebar.NO_FOLDER:
            self._title_widget.set_subtitle(_("No Folder"))
        elif self._doc_panel.is_drilled_in:
            self._title_widget.set_subtitle(os.path.basename(self._doc_panel._browsing_folder))
        else:
            self._title_widget.set_subtitle(os.path.basename(folder) if folder else "")

    def _on_file_created(self, _sidebar, path):
        if self._editing:
            text = self._editor.get_text()
            try:
                with open(self._current_file, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
            self._editing = False
            self._edit_btn.set_active(False)
            self._preview_btn.set_visible(False)
        self._load_file(path)
        self._edit_btn.set_active(True)

    def _on_file_selected(self, _panel, path):
        if self._editing:
            self._prompt_unsaved(path)
            return
        # Reset link navigation history when opening from the panel/search
        self._nav_history = [path]
        self._nav_index = 0
        self._load_file(path)

    def _on_viewer_link(self, _viewer, path):
        if self._editing:
            self._prompt_unsaved(path)
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
        """Open a file directly in view mode with sidebar hidden."""
        self._split_view.set_show_sidebar(False)
        self._load_file(path)
        # Show "Open root folder" in sidebar if file is outside the
        # persistent root (ceiling), not the session override.
        ceiling = os.path.realpath(os.path.expanduser(self._root_ceiling))
        file_dir = os.path.realpath(os.path.dirname(path))
        if file_dir != ceiling and not file_dir.startswith(ceiling + os.sep):
            self._sidebar.set_outside_root(True)

    def _load_file(self, path, push_history=False):
        if push_history:
            # Truncate forward history and append
            self._nav_history = self._nav_history[:self._nav_index + 1]
            self._nav_history.append(path)
            self._nav_index = len(self._nav_history) - 1
        self._current_file = path
        self._back_btn.set_visible(True)
        self._edit_btn.set_sensitive(True)
        self._copy_rich_btn.set_visible(True)
        self._open_in_btn.set_visible(True)
        self._export_pdf_action.set_enabled(True)
        self._toc_btn.set_visible(True)
        self._tags_btn.set_visible(True)
        self._title_widget.set_subtitle(os.path.basename(path))
        self._viewer.load_file(path)
        self._stack.set_visible_child_name("view")
        self._start_watching()
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self._update_stats(text)
            self._update_toc(text)
        except OSError:
            pass
        self._sync_nav_state()

    def _prompt_unsaved(self, next_path):
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

        dialog.connect("response", self._on_unsaved_response, next_path)
        dialog.present(self)

    def _on_unsaved_response(self, _dialog, response, next_path):
        if response == "cancel":
            return
        if response == "save":
            text = self._editor.get_text()
            try:
                with open(self._current_file, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
        # For both "save" and "discard"
        self._editing = False
        self._edit_btn.set_active(False)
        self._stack.set_visible_child_name("view")
        self._load_file(next_path)

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
        if not self._editing and self._current_file:
            self._viewer.load_file(self._current_file)

    def _on_file_trashed(self, _panel, path):
        self._tag_index.remove_file(path)
        if self._current_file == path:
            self._stop_watching()
            self._current_file = None
            self._editing = False
            self._edit_btn.set_active(False)
            self._edit_btn.set_sensitive(False)
            self._copy_rich_btn.set_visible(False)
            self._open_in_btn.set_visible(False)
            self._export_pdf_action.set_enabled(False)
            self._toc_btn.set_visible(False)
            self._tags_btn.set_visible(False)
            self._title_widget.set_subtitle("")
            self._status_bar.set_visible(False)
            self._stack.set_visible_child_name("documents")
        self._sidebar.refresh()

    def _on_file_renamed(self, _panel, old_path, new_path):
        self._tag_index.remove_file(old_path)
        self._tag_index.update_file(new_path)
        if self._current_file == old_path:
            self._current_file = new_path
            self._title_widget.set_subtitle(os.path.basename(new_path))
            self._start_watching()
        self._sidebar.refresh()

    def _on_settings_changed(self, _mgr, key):
        if key == "root_directory":
            # Update ceiling if this was a persistent change (not an override)
            persisted = self._settings._data.get("root_directory")
            if persisted and "root_directory" not in self._settings._overrides:
                self._root_ceiling = persisted
            self._tag_index.set_root(self._settings.root_directory)
            self._update_root_label()
            self._sidebar.refresh()
            self._doc_panel.refresh()
            self._welcome.refresh()
        elif key in ("font_family", "font_size", "viewer_theme"):
            self._viewer.update_style()
            self._preview_viewer.update_style()
        elif key in ("editor_font_family", "editor_font_size",
                     "editor_theme", "editor_line_numbers", "editor_line_wrap"):
            self._editor.update_style()
        elif key == "edit_shortcut":
            self._apply_edit_shortcut()
        elif key == "file_watching":
            if self._settings.file_watching:
                self._start_watching()
            else:
                self._stop_watching()
        elif key == "show_sidebar_tags":
            self._sidebar.refresh()
        elif key == "double_click_to_edit":
            enabled = self._settings.double_click_to_edit
            self._viewer.set_edit_on_dblclick(enabled)
            self._preview_viewer.set_edit_on_dblclick(enabled)

    def _on_preview_toggled(self, btn):
        active = btn.get_active()
        self._settings.set("preview_enabled", active)
        self._preview_viewer.set_visible(active)
        btn.set_icon_name(
            "stenmark-preview-symbolic" if active else "stenmark-preview-off-symbolic"
        )
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
                with open(self._current_file, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                return
        else:
            return

        from stenmark.markdown_renderer import MarkdownRenderer
        body = MarkdownRenderer().render(text)
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
        self._status_bar.set_visible(True)

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

    def _parse_headings(self, text):
        headings = []
        in_fence = False
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = re.match(r'^(#{1,6})\s+(.+)', line)
            if m:
                level = len(m.group(1))
                title = m.group(2).strip()
                headings.append((level, title, i))
        return headings

    def _update_toc(self, text):
        self._toc_headings = self._parse_headings(text)
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
        level, title, line_num = self._toc_headings[idx]
        if self._editing:
            self._editor._js(f"scrollToLine({line_num})")
        else:
            self._viewer._webview.evaluate_javascript(
                f"document.querySelectorAll('h1,h2,h3,h4,h5,h6')[{idx}]?.scrollIntoView({{behavior:'smooth'}});",
                -1, None, None, None, None,
            )

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
        """Show the tag filter pane, optionally pre-selecting a tag."""
        if self._editing:
            text = self._editor.get_text()
            try:
                with open(self._current_file, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
            self._editing = False
            self._edit_btn.set_active(False)
            self._preview_btn.set_visible(False)
        self._title_widget.set_subtitle(_("Tags"))
        self._edit_btn.set_sensitive(False)
        self._copy_rich_btn.set_visible(False)
        self._open_in_btn.set_visible(False)
        self._export_pdf_action.set_enabled(False)
        self._toc_btn.set_visible(False)
        self._tags_btn.set_visible(False)
        self._status_bar.set_visible(False)
        if preselect_tag:
            self._tag_panel.select_tag(preselect_tag)
        else:
            self._tag_panel.show_tags()
        self._stack.set_visible_child_name("tags")
        self._back_btn.set_visible(True)
        self._tag_panel.focus_entry()

    def _on_search(self, *_args):
        """Switch to the full-text search panel."""
        if self._editing:
            text = self._editor.get_text()
            try:
                with open(self._current_file, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
            self._editing = False
            self._edit_btn.set_active(False)
            self._preview_btn.set_visible(False)
        # Scope search to the currently selected folder
        folder = self._doc_panel._current_folder
        if folder:
            self._search_panel.set_folder(folder)
        self._title_widget.set_subtitle(_("Search"))
        self._edit_btn.set_sensitive(False)
        self._copy_rich_btn.set_visible(False)
        self._open_in_btn.set_visible(False)
        self._export_pdf_action.set_enabled(False)
        self._toc_btn.set_visible(False)
        self._tags_btn.set_visible(False)
        self._status_bar.set_visible(False)
        self._stack.set_visible_child_name("search")
        self._back_btn.set_visible(True)
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
        self._split_view.set_show_sidebar(True)

    # ---- Root folder navigation (sidebar header) -------------------------

    def _update_root_label(self):
        self._root_label.set_label(
            os.path.basename(self._settings.root_directory)
        )

    def _on_root_btn_toggled(self, btn, _pspec):
        if not btn.get_active():
            return

        from stenmark.sidebar import _collect_subdirs

        current_root = self._settings.root_directory
        ceiling = os.path.expanduser(self._root_ceiling)

        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            margin_start=4,
            margin_end=4,
            margin_top=4,
            margin_bottom=4,
        )

        # "Back" row if drilled deeper than ceiling
        if os.path.normpath(current_root) != os.path.normpath(ceiling):
            parent = os.path.dirname(current_root)
            back_btn = Gtk.Button(css_classes=["flat"])
            back_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                margin_start=6,
                margin_end=6,
                margin_top=4,
                margin_bottom=4,
            )
            back_box.append(Gtk.Image(icon_name="stenmark-go-previous-symbolic"))
            back_box.append(Gtk.Label(
                label=os.path.basename(parent) if parent != current_root else _("Back"),
                xalign=0,
                hexpand=True,
            ))
            back_btn.set_child(back_box)
            back_btn.connect("clicked", self._on_root_nav, parent)
            box.append(back_btn)
            box.append(Gtk.Separator())

        # Child folder rows
        subdirs = _collect_subdirs(current_root)
        if subdirs:
            for dir_path, dir_name in subdirs:
                btn = Gtk.Button(css_classes=["flat"])
                row_box = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL,
                    spacing=8,
                    margin_start=6,
                    margin_end=6,
                    margin_top=4,
                    margin_bottom=4,
                )
                row_box.append(Gtk.Image(icon_name="stenmark-folder-symbolic"))
                row_box.append(Gtk.Label(label=dir_name, xalign=0, hexpand=True))
                btn.set_child(row_box)
                btn.connect("clicked", self._on_root_nav, dir_path)
                box.append(btn)
        else:
            box.append(Gtk.Label(
                label=_("No subfolders"),
                css_classes=["dim-label"],
                margin_start=6,
                margin_end=6,
                margin_top=8,
                margin_bottom=8,
            ))

        self._root_popover.set_child(box)

    def _on_root_nav(self, _btn, dir_path):
        self._root_popover.popdown()
        self._settings.set_override("root_directory", dir_path)
