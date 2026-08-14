# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import json
import os
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GObject

DEFAULTS = {
    "root_directory": str(Path.home() / "Documents"),
    # Empty means "follow the system locale". See stenmark.i18n, which reads
    # this key straight from the file before any catalogue is loaded.
    "language": "",
    "font_family": "Sans",
    "font_size": 16,
    "theme": "system",
    "viewer_theme": "auto",
    "editor_font_family": "Monospace",
    "editor_font_size": 14,
    "editor_theme": "auto",
    "editor_line_numbers": True,
    "editor_line_wrap": True,
    "editor_typewriter": False,
    "double_click_to_edit": True,
    "hide_sidebar_on_edit": True,
    "edit_shortcut": "<Control>e",
    "typewriter_shortcut": "<Control><Shift>t",
    "pinned_files": [],
    "pinned_folders": [],
    "file_watching": True,
    "remember_last_folder": False,
    "show_sidebar_tags": False,
    "preview_enabled": False,
    "last_root_folder": "",
    # Version whose release notes have been shown. See whats_new_dialog.
    "whats_new_seen": "",
    "window_width": 1000,
    "window_height": 700,
}

# Honours XDG_CONFIG_HOME, which Flatpak points at the app's own state
# directory. Unset (the usual case) this is ~/.config, so a native install
# keeps the exact path it always had. Mirrored in i18n.py — keep in sync.
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "stenmark"
CONFIG_FILE = CONFIG_DIR / "settings.json"


class SettingsManager(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._data = dict(DEFAULTS)
        self._overrides = {}
        #: Whether this is the very first launch, sampled before anything can
        #: write the file. The what's-new dialog needs to tell a fresh install
        #: apart from an upgrade, and by the time it runs the file exists.
        self.first_run = not CONFIG_FILE.exists()
        self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    stored = json.load(f)
                for k, v in stored.items():
                    if k in DEFAULTS:
                        self._data[k] = v
            except (json.JSONDecodeError, OSError):
                pass
        # Ensure pinned_files / pinned_folders are always lists
        if not isinstance(self._data.get("pinned_files"), list):
            self._data["pinned_files"] = []
        if not isinstance(self._data.get("pinned_folders"), list):
            self._data["pinned_folders"] = []

    def _save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key):
        if key in self._overrides:
            return self._overrides[key]
        return self._data.get(key, DEFAULTS.get(key))

    def set_override(self, key, value):
        """Set a session-only override that is not persisted to disk."""
        self._overrides[key] = value
        self.emit("changed", key)

    def set(self, key, value):
        if self._data.get(key) != value:
            self._data[key] = value
            self._save()
            self.emit("changed", key)

    @property
    def root_directory(self):
        return os.path.expanduser(self.get("root_directory"))

    @property
    def font_family(self):
        return self.get("font_family")

    @property
    def font_size(self):
        return self.get("font_size")

    @property
    def theme(self):
        return self.get("theme")

    @property
    def viewer_theme(self):
        return self.get("viewer_theme")

    @property
    def editor_font_family(self):
        return self.get("editor_font_family")

    @property
    def editor_font_size(self):
        return self.get("editor_font_size")

    @property
    def editor_theme(self):
        return self.get("editor_theme")

    @property
    def editor_line_numbers(self):
        return self.get("editor_line_numbers")

    @property
    def editor_line_wrap(self):
        return self.get("editor_line_wrap")

    @property
    def editor_typewriter(self):
        return self.get("editor_typewriter")

    @property
    def double_click_to_edit(self):
        return self.get("double_click_to_edit")

    @property
    def hide_sidebar_on_edit(self):
        return self.get("hide_sidebar_on_edit")

    @property
    def pinned_files(self):
        return self.get("pinned_files")

    def is_pinned(self, path):
        return path in self.pinned_files

    def toggle_pin(self, path):
        pins = list(self.pinned_files)
        if path in pins:
            pins.remove(path)
        else:
            pins.append(path)
        self.set("pinned_files", pins)

    @property
    def pinned_folders(self):
        return self.get("pinned_folders")

    def is_folder_pinned(self, path):
        return path in self.pinned_folders

    def toggle_folder_pin(self, path):
        pins = list(self.pinned_folders)
        if path in pins:
            pins.remove(path)
        else:
            pins.append(path)
        self.set("pinned_folders", pins)

    def cleanup_stale_pins(self):
        """Remove pinned file/folder paths that no longer exist on disk."""
        changed = False

        valid_files = [p for p in self.pinned_files if os.path.exists(p)]
        if len(valid_files) != len(self.pinned_files):
            self._data["pinned_files"] = valid_files
            changed = True

        valid_folders = [p for p in self.pinned_folders if os.path.exists(p)]
        if len(valid_folders) != len(self.pinned_folders):
            self._data["pinned_folders"] = valid_folders
            changed = True

        if changed:
            self._save()

    @property
    def edit_shortcut(self):
        return self.get("edit_shortcut")

    @property
    def typewriter_shortcut(self):
        return self.get("typewriter_shortcut")

    @property
    def file_watching(self):
        return self.get("file_watching")

    @property
    def window_width(self):
        return self.get("window_width")

    @property
    def window_height(self):
        return self.get("window_height")
