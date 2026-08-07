# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib


class FileWatcher:
    DEBOUNCE_MS = 500

    def __init__(self, path, callback):
        self._callback = callback
        self._debounce_id = None

        gfile = Gio.File.new_for_path(path)
        self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", self._on_changed)

    def _on_changed(self, _monitor, _file, _other, event):
        if event in (
            Gio.FileMonitorEvent.CHANGED,
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
        ):
            self._debounce()

    def _debounce(self):
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(self.DEBOUNCE_MS, self._fire)

    def _fire(self):
        self._debounce_id = None
        self._callback()
        return GLib.SOURCE_REMOVE

    def stop(self):
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
        self._monitor.cancel()
