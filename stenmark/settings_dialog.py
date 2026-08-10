# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Gio

from stenmark.editor import available_themes, theme_colors
from stenmark.i18n import (_, LANGUAGE_KEY, SUPPORTED_LANGUAGES,
                           TRANSLATE_URL)


class ThemePreview(Gtk.DrawingArea):
    """A mock editor line drawn in a theme's own colours.

    The editor itself is only a live preview when it happens to be on screen —
    open Preferences from the document list and changing the theme shows
    nothing at all. This does not care what is behind the dialog.
    """

    _HEIGHT = 88
    _GUTTER = 20
    _LINES = (0.52, 0.70, 0.38, 0.61)

    def __init__(self):
        super().__init__()
        self.set_content_height(self._HEIGHT)
        self.set_hexpand(True)
        self.add_css_class("card")
        self._colors = {}
        self.set_draw_func(self._draw)

    def set_colors(self, colors):
        self._colors = colors or {}
        self.queue_draw()

    def _rgba(self, field, fallback):
        rgba = Gdk.RGBA()
        value = self._colors.get(field)
        if value and rgba.parse(value):
            return rgba
        rgba.parse(fallback)
        return rgba

    @staticmethod
    def _set(cr, rgba, alpha=1.0):
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha * alpha)

    @staticmethod
    def _rounded(cr, x, y, w, h, r):
        import math
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _draw(self, _area, cr, width, height):
        bg = self._rgba("background", "#ffffff")
        fg = self._rgba("foreground", "#2e2e2e")
        gutter = self._rgba("gutterBackground", "#f0f0f0")
        caret = self._rgba("caret", "#2e2e2e")
        selection = self._rgba("selection", "#c8def5")
        line_hl = self._rgba("lineHighlight", "rgba(0,0,0,0.04)")

        self._rounded(cr, 0, 0, width, height, 8)
        cr.clip()

        self._set(cr, bg)
        cr.paint()

        self._set(cr, gutter)
        cr.rectangle(0, 0, self._GUTTER, height)
        cr.fill()

        top, step, bar_h = 14, 16, 6
        text_x = self._GUTTER + 10
        avail = width - text_x - 14

        # active line band
        self._set(cr, line_hl)
        cr.rectangle(0, top - 4, width, step)
        cr.fill()

        for i, frac in enumerate(self._LINES):
            y = top + i * step
            # line number
            self._set(cr, fg, 0.35)
            cr.rectangle(7, y, 6, bar_h)
            cr.fill()
            # selection sits behind the third line
            if i == 2:
                self._set(cr, selection)
                cr.rectangle(text_x - 3, y - 3, avail * frac + 6, bar_h + 6)
                cr.fill()
            # alternating emphasis stands in for syntax colouring
            self._set(cr, fg, 0.9 if i % 2 == 0 else 0.55)
            cr.rectangle(text_x, y, avail * frac, bar_h)
            cr.fill()

        # caret at the end of the first line
        self._set(cr, caret)
        cr.rectangle(text_x + avail * self._LINES[0] + 4, top - 2, 2, bar_h + 4)
        cr.fill()


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, settings):
        super().__init__(title=_("Preferences"))
        self._settings = settings
        self._build_ui()

    def _build_ui(self):
        # --- General page ---
        general_page = Adw.PreferencesPage(
            title=_("General"),
            icon_name="preferences-other-symbolic",
        )

        # Directory group
        dir_group = Adw.PreferencesGroup(title=_("Files"))

        dir_row = Adw.ActionRow(title=_("Root Directory"))
        dir_row.set_subtitle(self._settings.get("root_directory"))
        dir_row.set_subtitle_lines(1)
        dir_row.add_css_class("property")
        choose_btn = Gtk.Button(
            icon_name="folder-open-symbolic",
            valign=Gtk.Align.CENTER,
        )
        choose_btn.connect("clicked", self._on_choose_root_dir)
        dir_row.add_suffix(choose_btn)
        dir_row.set_activatable_widget(choose_btn)
        self._dir_row = dir_row
        dir_group.add(dir_row)

        watch_row = Adw.SwitchRow(
            title=_("File Watching"),
            subtitle=_("Auto-reload when files change on disk"),
        )
        watch_row.set_active(self._settings.file_watching)
        watch_row.connect("notify::active", self._on_file_watching_changed)
        dir_group.add(watch_row)

        remember_row = Adw.SwitchRow(
            title=_("Remember Last Folder"),
            subtitle=_("Restore the last navigated folder on startup"),
        )
        remember_row.set_active(self._settings.get("remember_last_folder"))
        remember_row.connect(
            "notify::active",
            lambda row, _p: self._settings.set("remember_last_folder", row.get_active()),
        )
        dir_group.add(remember_row)

        sidebar_tags_row = Adw.SwitchRow(
            title=_("Show Tags in Sidebar"),
            subtitle=_("Display tags section in the sidebar"),
        )
        sidebar_tags_row.set_active(self._settings.get("show_sidebar_tags"))
        sidebar_tags_row.connect(
            "notify::active",
            lambda row, _p: self._settings.set("show_sidebar_tags", row.get_active()),
        )
        dir_group.add(sidebar_tags_row)

        general_page.add(dir_group)

        # Theme group
        theme_group = Adw.PreferencesGroup(title=_("Appearance"))

        # "System default" first, then each language named in itself — a
        # German speaker looking for German should not have to know the
        # English word for it.
        self._language_codes = [""] + [c for c, _label in SUPPORTED_LANGUAGES]
        labels = [_("System default")] + [label for _c, label in SUPPORTED_LANGUAGES]

        self._language_row = Adw.ComboRow(
            title=_("Language"),
            subtitle=_("Applied when Stenmark restarts"),
        )
        self._language_row.set_model(Gtk.StringList.new(labels))
        saved_lang = self._settings.get(LANGUAGE_KEY) or ""
        self._language_row.set_selected(
            self._language_codes.index(saved_lang)
            if saved_lang in self._language_codes else 0
        )
        self._language_row.connect("notify::selected", self._on_language_changed)
        theme_group.add(self._language_row)

        # Right under the dropdown, because someone who just opened it and did
        # not find their language is exactly the person worth asking — and the
        # barrier worth naming is that it is a text file, not a build.
        translate_row = Adw.ActionRow(
            title=_("Your language missing?"),
            subtitle=_("Stenmark can be translated into any language — it's a "
                       "text file, not code."),
            activatable=True,
        )
        translate_row.add_suffix(Gtk.Image(icon_name="adw-external-link-symbolic"))
        translate_row.connect(
            "activated",
            lambda *_a: Gtk.UriLauncher(uri=TRANSLATE_URL).launch(
                self.get_root(), None, None, None
            ),
        )
        theme_group.add(translate_row)

        theme_row = Adw.ComboRow(title=_("App Theme"))
        theme_list = Gtk.StringList.new([_("System"), _("Light"), _("Dark")])
        theme_row.set_model(theme_list)
        idx = {"system": 0, "light": 1, "dark": 2}.get(self._settings.theme, 0)
        theme_row.set_selected(idx)
        theme_row.connect("notify::selected", self._on_theme_changed)
        theme_group.add(theme_row)
        self._theme_row = theme_row

        viewer_theme_row = Adw.ComboRow(title=_("Viewer Theme"))
        viewer_theme_row.set_subtitle(_("Style used when reading documents"))
        # Theme names are proper nouns (GitHub, Solarized) — only "Auto" is a
        # word rather than a name, so it is the only one translated.
        _VIEWER_THEMES = [
            (_("Auto"), "auto"),
            ("GitHub", "github"),
            ("GitHub Dark", "github-dark"),
            ("Sepia", "sepia"),
            ("Solarized Light", "solarized-light"),
            ("Solarized Dark", "solarized-dark"),
        ]
        viewer_theme_row.set_model(
            Gtk.StringList.new([label for label, _key in _VIEWER_THEMES])
        )
        viewer_theme_keys = [key for _label, key in _VIEWER_THEMES]
        current_vt = self._settings.viewer_theme
        viewer_theme_row.set_selected(
            viewer_theme_keys.index(current_vt) if current_vt in viewer_theme_keys else 0
        )
        viewer_theme_row.connect(
            "notify::selected",
            lambda row, _p: self._settings.set(
                "viewer_theme", viewer_theme_keys[row.get_selected()]
            ),
        )
        theme_group.add(viewer_theme_row)

        general_page.add(theme_group)
        self.add(general_page)

        # --- Fonts page ---
        fonts_page = Adw.PreferencesPage(
            title=_("Fonts"),
            icon_name="font-select-symbolic",
        )

        viewer_group = Adw.PreferencesGroup(title=_("Viewer Font"))

        font_row = Adw.EntryRow(title=_("Font Family"))
        font_row.set_text(self._settings.font_family)
        font_row.connect("changed", self._on_font_family_changed)
        viewer_group.add(font_row)

        size_row = Adw.SpinRow.new_with_range(8, 32, 1)
        size_row.set_title(_("Font Size"))
        size_row.set_value(self._settings.font_size)
        size_row.connect("notify::value", self._on_font_size_changed)
        viewer_group.add(size_row)

        fonts_page.add(viewer_group)

        editor_group = Adw.PreferencesGroup(title=_("Editor Font"))

        ed_font_row = Adw.EntryRow(title=_("Font Family"))
        ed_font_row.set_text(self._settings.editor_font_family)
        ed_font_row.connect("changed", self._on_editor_font_family_changed)
        editor_group.add(ed_font_row)

        ed_size_row = Adw.SpinRow.new_with_range(8, 32, 1)
        ed_size_row.set_title(_("Font Size"))
        ed_size_row.set_value(self._settings.editor_font_size)
        ed_size_row.connect("notify::value", self._on_editor_font_size_changed)
        editor_group.add(ed_size_row)

        fonts_page.add(editor_group)
        self.add(fonts_page)

        # --- Editor page ---
        editor_page = Adw.PreferencesPage(
            title=_("Editor"),
            icon_name="text-editor-symbolic",
        )

        editor_appearance_group = Adw.PreferencesGroup(title=_("Appearance"))

        # Read from the bundle's own theme manifest. Names are proper nouns
        # (Dracula, Nord, Xcode) and stay untranslated — "Auto" is the one
        # word rather than a name, as with the viewer themes above.
        _EDITOR_THEMES = [
            (_("Auto") if key == "auto" else label, key)
            for key, label in available_themes()
        ]
        self._editor_theme_keys = [key for _label, key in _EDITOR_THEMES]

        theme_row = Adw.ComboRow(title=_("Color Theme"))
        theme_row.set_model(
            Gtk.StringList.new([label for label, _key in _EDITOR_THEMES])
        )
        # Long enough to be worth typing into
        if hasattr(theme_row, "set_enable_search"):
            theme_row.set_enable_search(True)
        current_et = self._settings.editor_theme
        theme_row.set_selected(
            self._editor_theme_keys.index(current_et)
            if current_et in self._editor_theme_keys else 0
        )
        theme_row.connect("notify::selected", self._on_editor_theme_changed)
        editor_appearance_group.add(theme_row)

        self._theme_preview = ThemePreview()
        self._theme_preview.set_margin_top(12)
        editor_appearance_group.add(self._theme_preview)
        self._update_theme_preview(current_et)

        line_numbers_row = Adw.SwitchRow(title=_("Line Numbers"))
        line_numbers_row.set_active(self._settings.editor_line_numbers)
        line_numbers_row.connect("notify::active", self._on_line_numbers_changed)
        editor_appearance_group.add(line_numbers_row)

        line_wrap_row = Adw.SwitchRow(title=_("Line Wrap"))
        line_wrap_row.set_active(self._settings.editor_line_wrap)
        line_wrap_row.connect("notify::active", self._on_line_wrap_changed)
        editor_appearance_group.add(line_wrap_row)

        editor_page.add(editor_appearance_group)

        editor_behaviour_group = Adw.PreferencesGroup(title=_("Behaviour"))

        dblclick_row = Adw.SwitchRow(
            title=_("Double-Click to Edit"),
            subtitle=_("Double-clicking text in the reader opens the editor at that spot"),
        )
        dblclick_row.set_active(self._settings.double_click_to_edit)
        dblclick_row.connect("notify::active", self._on_double_click_to_edit_changed)
        editor_behaviour_group.add(dblclick_row)

        hide_sidebar_row = Adw.SwitchRow(
            title=_("Hide Sidebar While Editing"),
            subtitle=_("Gives the editor and preview pane the full window width"),
        )
        hide_sidebar_row.set_active(self._settings.hide_sidebar_on_edit)
        hide_sidebar_row.connect("notify::active", self._on_hide_sidebar_on_edit_changed)
        editor_behaviour_group.add(hide_sidebar_row)

        editor_page.add(editor_behaviour_group)

        editor_shortcuts_group = Adw.PreferencesGroup(title=_("Shortcuts"))

        edit_shortcut_row = Adw.EntryRow(title=_("Toggle Edit Mode"))
        edit_shortcut_row.set_text(self._settings.edit_shortcut)
        edit_shortcut_row.connect("changed", self._on_edit_shortcut_changed)
        editor_shortcuts_group.add(edit_shortcut_row)

        editor_page.add(editor_shortcuts_group)
        self.add(editor_page)
        self._editor_page = editor_page

    def _on_choose_root_dir(self, _btn):
        dialog = Gtk.FileDialog(title=_("Choose Root Directory"))
        current = Gio.File.new_for_path(self._settings.root_directory)
        dialog.set_initial_folder(current)
        dialog.select_folder(self.get_root(), None, self._on_root_dir_selected)

    def _on_root_dir_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except Exception:
            return
        path = folder.get_path()
        self._settings.set("root_directory", path)
        self._dir_row.set_subtitle(path)

    def _on_language_changed(self, row, _pspec):
        idx = row.get_selected()
        if idx >= len(self._language_codes):
            return
        code = self._language_codes[idx]
        if code == (self._settings.get(LANGUAGE_KEY) or ""):
            return
        self._settings.set(LANGUAGE_KEY, code)

        # gettext resolves each string when its widget is built, so nothing
        # already on screen can change language in place. Restarting is the
        # honest way to apply it.
        dlg = Adw.AlertDialog(
            heading=_("Restart Stenmark?"),
            body=_("The new language takes effect after Stenmark restarts."),
        )
        dlg.add_response("later", _("Later"))
        dlg.add_response("restart", _("Restart Now"))
        dlg.set_response_appearance("restart", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("restart")
        dlg.set_close_response("later")
        dlg.connect("response", self._on_restart_response)
        dlg.present(self.get_root() or self)

    def _on_restart_response(self, _dlg, response):
        if response != "restart":
            return
        # An unsaved edit buffer only lives in the editor widget, so a restart
        # would drop it silently. Say so and let them deal with it first.
        if self._editing_windows():
            warn = Adw.AlertDialog(
                heading=_("Unsaved Changes"),
                body=_("Save your open document before restarting."),
            )
            warn.add_response("ok", _("OK"))
            warn.present(self.get_root() or self)
            return
        self.close()
        GLib.idle_add(self._restart)

    def _editing_windows(self):
        """Windows currently in edit mode, i.e. holding an unsaved buffer."""
        # Not via get_root(): presented parentless the dialog lives in a window
        # of its own, which carries no application — and silently returning no
        # windows here would drop the unsaved-buffer warning before a restart.
        app = Gio.Application.get_default()
        if app is None:
            return []
        return [w for w in app.get_windows() if getattr(w, "_editing", False)]

    @staticmethod
    def _restart():
        import os
        import sys
        # execv replaces this process, so the single-instance lock is released
        # with it — a fresh Stenmark comes up rather than a second one handing
        # off to the corpse of the old.
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except OSError:
            pass
        return GLib.SOURCE_REMOVE

    def _on_file_watching_changed(self, row, _pspec):
        self._settings.set("file_watching", row.get_active())

    def _on_theme_changed(self, row, _pspec):
        themes = ["system", "light", "dark"]
        self._settings.set("theme", themes[row.get_selected()])

    def _on_font_family_changed(self, row):
        self._settings.set("font_family", row.get_text())

    def _on_font_size_changed(self, row, _pspec):
        self._settings.set("font_size", int(row.get_value()))

    def _on_editor_font_family_changed(self, row):
        self._settings.set("editor_font_family", row.get_text())

    def _on_editor_font_size_changed(self, row, _pspec):
        self._settings.set("editor_font_size", int(row.get_value()))

    def _update_theme_preview(self, key):
        dark = Adw.StyleManager.get_default().get_dark()
        self._theme_preview.set_colors(theme_colors(key, system_dark=dark))

    def _on_editor_theme_changed(self, row, _pspec):
        key = self._editor_theme_keys[row.get_selected()]
        self._settings.set("editor_theme", key)
        self._update_theme_preview(key)

    def _on_line_numbers_changed(self, row, _pspec):
        self._settings.set("editor_line_numbers", row.get_active())

    def _on_line_wrap_changed(self, row, _pspec):
        self._settings.set("editor_line_wrap", row.get_active())

    def _on_double_click_to_edit_changed(self, row, _pspec):
        self._settings.set("double_click_to_edit", row.get_active())

    def _on_hide_sidebar_on_edit_changed(self, row, _pspec):
        self._settings.set("hide_sidebar_on_edit", row.get_active())

    def _on_edit_shortcut_changed(self, row):
        self._settings.set("edit_shortcut", row.get_text())
