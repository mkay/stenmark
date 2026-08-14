# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

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
            /* Zebra striping for the root selector's popup. The stripe goes on
               the box built in the factory, never on the row: a GtkListView
               row inside a dropdown popup accepts almost nothing from an app
               provider — background, margin, border-radius and padding are
               all dropped silently, which is what made the first attempt at
               this invisible. A solid background on the row never paints.
               That also leaves the row's own 6px of padding in place with no
               way to remove it, so the box could only ever fill the content
               box inside it and every stripe was ringed by a dead 6px band.
               The negative margin pulls the box back out over that padding:
               the stripes now meet vertically and reach the popover's edges.
               Row height is 23px of content plus twice the padding below, and
               the horizontal padding carries the 6px back so text still sits
               10px from the edge. currentColor is the text colour, so the
               tint is white-on-dark and black-on-light with no second rule
               and nothing to reload when the theme flips. */
            .root-dropdown popover listview > row > box {
                margin: -6px;
                padding: 6px 16px;
            }
            .root-row-alt {
                background-color: color-mix(in srgb, currentColor 3.5%, transparent);
            }
            /* Under the pointer the theme draws its own rounded pill on the
               row, and a striped box underneath leaves its square corners
               poking out around it. Drop the stripe for those states and let
               the pill stand alone. */
            .root-dropdown popover listview > row:hover > box,
            .root-dropdown popover listview > row:active > box {
                background-color: transparent;
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

