# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Gio

from stenmark import APP_ID, APP_NAME, VERSION
from stenmark.i18n import _
from stenmark.settings_manager import SettingsManager


class Application(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.settings = SettingsManager()

        self._open_file = None  # path to a .md file passed on the CLI

        self.set_option_context_parameter_string(_("[FOLDER | FILE.md]"))
        self.set_option_context_summary(
            _("Open a folder of Markdown files for reading and editing.\n"
              "If FOLDER is given, it is used as the root directory for this "
              "session only.\n"
              "If a .md file is given, it is opened directly in view mode.")
        )

        self.add_main_option(
            "version", ord("v"),
            GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            _("Show the application version"), None,
        )

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._apply_theme()
        self.settings.connect("changed", self._on_settings_changed)
        self._register_icons()
        self._load_css()
        self._setup_actions()

    def _setup_actions(self):
        new_window = Gio.SimpleAction.new("new-window", None)
        new_window.connect("activate", self._on_new_window)
        self.add_action(new_window)
        self.set_accels_for_action("app.new-window", ["<Control><Shift>n"])

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        support = Gio.SimpleAction.new("support", None)
        support.connect("activate", self._on_support)
        self.add_action(support)

        window_size = Gio.SimpleAction.new("window-size", None)
        window_size.connect("activate", self._on_window_size)
        self.add_action(window_size)

    def _register_icons(self):
        pkg_dir = Path(__file__).parent
        gresource = pkg_dir / "data" / "de.singular.stenmark.gresource"
        gresource_xml = pkg_dir / "data" / "de.singular.stenmark.gresource.xml"
        if not gresource.exists() and gresource_xml.exists():
            # Dev mode: compile the gresource on the fly
            import subprocess  # nosec B404
            subprocess.run(  # nosec B603 B607
                ["glib-compile-resources",
                 f"--sourcedir={pkg_dir / 'data'}",
                 str(gresource_xml),
                 f"--target={gresource}"],
                check=True,
            )
        if gresource.exists():
            Gio.resources_register(Gio.resource_load(str(gresource)))
            Gtk.IconTheme.get_for_display(
                Gdk.Display.get_default()
            ).add_resource_path("/de/singular/stenmark/icons/hicolor")

    def _load_css(self):
        css = Gtk.CssProvider()
        css.load_from_string("""
            .app-sidebar { background-color: shade(@window_bg_color, 0.97); }
            .tag-chip {
                background: alpha(@accent_color, 0.15);
                border-radius: 9999px;
                padding: 0 8px;
                min-height: 20px;
                font-size: 0.8em;
            }
            flowboxchild:has(.tag-chip) {
                padding: 0;
                margin: 0;
            }
            .tag-chip-link {
                background: alpha(@accent_color, 0.12);
                color: alpha(@accent_color, 0.85);
                border-radius: 4px;
                padding: 1px 6px;
            }
            .tag-chip-link:hover {
                background: alpha(@accent_color, 0.22);
                color: @accent_color;
            }
            .tag-filter-chip {
                border-radius: 9999px;
                padding: 2px 10px;
                font-size: 0.85em;
                min-height: 0;
            }
            .navigation-sidebar row.sidebar-divider,
            .navigation-sidebar row.sidebar-divider:hover,
            .navigation-sidebar row.sidebar-divider:focus,
            .navigation-sidebar row.sidebar-divider:active {
                background: none;
                outline: none;
                box-shadow: none;
                min-height: 0;
                padding: 0;
            }
            .tag-filter-chip:checked {
                background: alpha(@accent_color, 0.25);
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _apply_theme(self):
        style = self.get_style_manager()
        theme = self.settings.theme
        if theme == "dark":
            style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        elif theme == "light":
            style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _on_settings_changed(self, _mgr, key):
        if key == "theme":
            self._apply_theme()

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        if options.lookup_value("version"):
            print(f"{APP_NAME} {VERSION}")
            return 0

        args = command_line.get_arguments()[1:]
        if args:
            path = Path(args[0]).expanduser().resolve()
            if path.is_dir():
                self.settings.set_override("root_directory", str(path))
                self.settings.cli_root = True
            elif path.is_file() and path.suffix.lower() == ".md":
                self._open_file = str(path)
                # Set root to the file's parent directory for this session
                self.settings.set_override("root_directory", str(path.parent))
                self.settings.cli_root = True
        self.do_activate()
        return 0

    def do_activate(self):
        win = self.get_active_window()
        first_window = win is None
        if not win:
            from stenmark.window import MainWindow
            open_file = self._open_file
            self._open_file = None
            win = MainWindow(application=self, settings=self.settings,
                             open_file=open_file)
        elif self._open_file:
            win.open_file(self._open_file)
            self._open_file = None
        win.present()

        if first_window:
            # After present(), and on an idle callback: Adw.Dialog needs a
            # realized parent to attach to.
            from stenmark.whats_new_dialog import present_if_updated
            GLib.idle_add(present_if_updated, win, self.settings,
                          self.settings.first_run)

    def _on_support(self, _action, _param):
        win = self.props.active_window
        if not win:
            return
        from stenmark import support_dialog
        support_dialog.present(win)

    def _on_new_window(self, _action, _param):
        from stenmark.window import MainWindow
        win = MainWindow(application=self, settings=self.settings)
        win.present()

    def _on_window_size(self, _action, _param):
        win = self.props.active_window
        if not win:
            return

        dialog = Adw.Dialog(title=_("Window Size"), content_width=320, content_height=220)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.connect("clicked", lambda _: dialog.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=_("Save"), css_classes=["suggested-action"])
        header.pack_end(save_btn)
        toolbar_view.add_top_bar(header)

        clamp = Adw.Clamp(maximum_size=320, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        group = Adw.PreferencesGroup()

        width_row = Adw.SpinRow(
            title=_("Width"),
            adjustment=Gtk.Adjustment(value=self.settings.window_width, lower=800, upper=3840, step_increment=10),
        )
        group.add(width_row)

        height_row = Adw.SpinRow(
            title=_("Height"),
            adjustment=Gtk.Adjustment(value=self.settings.window_height, lower=600, upper=2160, step_increment=10),
        )
        group.add(height_row)

        clamp.set_child(group)
        toolbar_view.set_content(clamp)
        dialog.set_child(toolbar_view)

        def on_save(_):
            self.settings.set("window_width", int(width_row.get_value()))
            self.settings.set("window_height", int(height_row.get_value()))
            dialog.close()

        save_btn.connect("clicked", on_save)
        dialog.present(win)
