# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-only

import json
import os

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, GLib, Gtk, WebKit

from stenmark.i18n import _


_EDITOR_HTML = os.path.join(
    os.path.dirname(__file__), "data", "editor", "editor.html"
)


class MarkdownEditor(Gtk.Box):
    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._settings = settings
        self._text_cache = ""
        self._ready = False
        self._pending_text = None
        # (line, word, center) requested before the document was in place
        self._pending_goto = None
        self._save_callback = None
        self._preview_callback = None
        self._scroll_callback = None
        self._escape_callback = None

        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("textChanged")
        ucm.register_script_message_handler("saveRequest")
        ucm.register_script_message_handler("scrollLine")
        ucm.register_script_message_handler("escapeRequest")
        ucm.connect("script-message-received::textChanged", self._on_text_changed)
        ucm.connect("script-message-received::saveRequest", self._on_save_request)
        ucm.connect("script-message-received::scrollLine", self._on_scroll_line)
        ucm.connect("script-message-received::escapeRequest", self._on_escape_request)

        self._webview = WebKit.WebView(user_content_manager=ucm)
        self._webview.set_vexpand(True)
        self._webview.set_hexpand(True)
        self._webview.connect("load-changed", self._on_load_changed)

        ws = self._webview.get_settings()
        ws.set_enable_developer_extras(False)

        # Workaround: WebKit GTK may swallow backtick (dead_grave)
        # key events before they reach CodeMirror.  Intercept at
        # the GTK level and inject via JS.
        self._dead_key = None
        key_ctl = Gtk.EventControllerKey()
        key_ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctl.connect("key-pressed", self._on_key_pressed)
        self._webview.add_controller(key_ctl)

        self.prepend(self._build_toolbar())
        self.append(self._webview)

        Adw.StyleManager.get_default().connect("notify::dark", self._on_dark_changed)

        self._webview.load_uri(f"file://{_EDITOR_HTML}")

    # ------------------------------------------------------------------
    # Toolbar

    def _build_toolbar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.add_css_class("toolbar")

        def btn(icon=None, label=None, tip=None, js=None):
            b = Gtk.Button()
            b.add_css_class("flat")
            b.set_focus_on_click(False)
            if icon:
                b.set_child(Gtk.Image(icon_name=icon))
            else:
                lbl = Gtk.Label(label=label)
                lbl.add_css_class("caption")
                lbl.add_css_class("monospace")
                b.set_child(lbl)
            if tip:
                b.set_tooltip_text(tip)
            if js:
                b.connect("clicked", lambda _b, s=js: self._js(s))
            return b

        def sep():
            s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            s.set_margin_top(6)
            s.set_margin_bottom(6)
            s.set_margin_start(4)
            s.set_margin_end(4)
            return s

        # Headings
        bar.append(btn(icon="stenmark-heading-1-symbolic", tip=_("Heading 1"), js="window.formatHeading(1)"))
        bar.append(btn(icon="stenmark-heading-2-symbolic", tip=_("Heading 2"), js="window.formatHeading(2)"))
        bar.append(btn(icon="stenmark-heading-3-symbolic", tip=_("Heading 3"), js="window.formatHeading(3)"))
        bar.append(sep())

        # Inline formatting
        bar.append(btn(icon="stenmark-format-bold-symbolic",          tip=_("Bold (Ctrl+B)"),             js="window.formatBold()"))
        bar.append(btn(icon="stenmark-format-italic-symbolic",        tip=_("Italic (Ctrl+I)"),           js="window.formatItalic()"))
        bar.append(btn(icon="stenmark-format-strikethrough-symbolic", tip=_("Strikethrough"),              js="window.formatStrike()"))
        bar.append(btn(icon="stenmark-format-code-symbolic",          tip=_("Inline code (Ctrl+`)"),      js="window.formatCode()"))
        bar.append(btn(icon="stenmark-format-code-block-symbolic",    tip=_("Code block (Ctrl+Shift+K)"), js="window.formatCodeBlock()"))
        bar.append(sep())

        # Block inserts
        bar.append(btn(icon="stenmark-insert-link-symbolic",          tip=_("Link (Ctrl+K)"),             js="window.formatLink()"))
        bar.append(btn(icon="stenmark-format-quote-symbolic",         tip=_("Blockquote"),                js="window.formatQuote()"))
        bar.append(sep())

        # Lists
        bar.append(btn(icon="stenmark-list-bullet-symbolic",    tip=_("Bullet list (Ctrl+Shift+U)"),   js="window.formatBullet()"))
        bar.append(btn(icon="stenmark-list-ordered-symbolic",   tip=_("Numbered list (Ctrl+Shift+O)"), js="window.formatNumbered()"))

        return bar

    # ------------------------------------------------------------------
    # Internal

    def _on_load_changed(self, _webview, event):
        if event != WebKit.LoadEvent.FINISHED:
            return
        self._ready = True
        GLib.idle_add(self._post_load_init)

    def _post_load_init(self):
        self._apply_style_js()
        if self._pending_text is not None:
            self._js_set_content(self._pending_text)
            self._pending_text = None
        self._flush_goto()
        return GLib.SOURCE_REMOVE

    def _on_text_changed(self, _ucm, result):
        self._text_cache = result.to_string()
        if self._preview_callback:
            self._preview_callback(self._text_cache)

    def _on_save_request(self, _ucm, _result):
        if self._save_callback:
            self._save_callback()

    def _on_escape_request(self, _ucm, _result):
        if self._escape_callback:
            self._escape_callback()

    def _on_scroll_line(self, _ucm, result):
        try:
            line = int(result.to_string())
        except (ValueError, TypeError):
            return
        if self._scroll_callback:
            self._scroll_callback(line)

    # Dead-key / backtick interception --------------------------------

    _DEAD_KEY_MAP = {
        Gdk.KEY_dead_grave: "`",
        Gdk.KEY_dead_acute: "'",
        Gdk.KEY_dead_circumflex: "^",
        Gdk.KEY_dead_tilde: "~",
        Gdk.KEY_dead_diaeresis: '"',
    }

    def _on_key_pressed(self, _ctl, keyval, _keycode, state):
        mods = state & (
            Gdk.ModifierType.CONTROL_MASK
            | Gdk.ModifierType.ALT_MASK
            | Gdk.ModifierType.META_MASK
        )
        # Direct backtick key (layouts where ` is not a dead key)
        if keyval == Gdk.KEY_grave and not mods:
            self._js(f"window.insertText({json.dumps('`')})")
            return True
        # Dead key press — remember it
        if keyval in self._DEAD_KEY_MAP and not mods:
            self._dead_key = keyval
            return True
        # Key after a dead key
        if self._dead_key is not None:
            dk = self._dead_key
            self._dead_key = None
            if keyval == Gdk.KEY_space:
                # dead key + space → literal character
                char = self._DEAD_KEY_MAP[dk]
                self._js(f"window.insertText({json.dumps(char)})")
                return True
            # dead key + letter → composed character (e.g. è, ñ)
            #
            # Only printable keys compose. Gdk.keyval_to_unicode() reports a
            # codepoint for control keys too — Escape is 27, Backspace 8,
            # Return 13 — so an unguarded check swallows them and inserts a
            # control character into the document instead. A pending dead key
            # followed by Escape used to leave edit mode unexitable.
            composed = Gdk.keyval_to_unicode(keyval)
            if composed and composed >= 32 and composed != 127:
                letter = chr(composed)
                import unicodedata
                accent_map = {
                    Gdk.KEY_dead_grave: "\u0300",
                    Gdk.KEY_dead_acute: "\u0301",
                    Gdk.KEY_dead_circumflex: "\u0302",
                    Gdk.KEY_dead_tilde: "\u0303",
                    Gdk.KEY_dead_diaeresis: "\u0308",
                }
                combining = accent_map.get(dk)
                if combining:
                    result = unicodedata.normalize("NFC", letter + combining)
                    self._js(f"window.insertText({json.dumps(result)})")
                    return True
            return False
        return False

    def _on_dark_changed(self, *_):
        self.update_style()

    def _js(self, script):
        if self._ready:
            self._webview.evaluate_javascript(script, -1, None, None, None, None)

    def _js_set_content(self, text):
        self._js(f"setContent({json.dumps(text)})")

    def _apply_style_js(self):
        dark = Adw.StyleManager.get_default().get_dark()
        theme = json.dumps(self._settings.editor_theme)
        dark_js = "true" if dark else "false"
        family = json.dumps(self._settings.editor_font_family)
        size = self._settings.editor_font_size
        line_nums = "true" if self._settings.editor_line_numbers else "false"
        line_wrap = "true" if self._settings.editor_line_wrap else "false"
        self._js(
            f"setTheme({theme}, {dark_js});"
            f"setFont({family}, {size});"
            f"setLineNumbers({line_nums});"
            f"setLineWrap({line_wrap});"
        )

    # ------------------------------------------------------------------
    # Public API (same surface as the old GtkSource editor)

    def load_text(self, text):
        self._text_cache = text
        self._pending_text = text
        if self._ready:
            GLib.idle_add(self._flush_pending)

    def _flush_pending(self):
        if self._pending_text is not None:
            self._js_set_content(self._pending_text)
            self._pending_text = None
        self._flush_goto()
        return GLib.SOURCE_REMOVE

    def goto_line(self, line, word="", center=False):
        """Put the caret on `line` (at `word`, if found there).

        Safe to call right after load_text() — the jump is held back until
        the document has actually been handed to CodeMirror.
        """
        self._pending_goto = (int(line or 1), word or "", bool(center))
        if self._ready and self._pending_text is None:
            self._flush_goto()

    def _flush_goto(self):
        if self._pending_goto is None:
            return
        line, word, center = self._pending_goto
        self._pending_goto = None
        self._js(
            f"window.gotoLine({line}, {json.dumps(word)}, "
            f"{'true' if center else 'false'})"
        )

    def focus_editor(self):
        """Give the editor keyboard focus, at the GTK level as well.

        CodeMirror's own view.focus() is not enough: unless the WebView holds
        the window's focus, keys never reach the page at all — which left
        Escape doing nothing until the user clicked into the text.
        """
        self._webview.grab_focus()
        self._js("window.focusEditor && window.focusEditor()")

    def get_top_line(self, callback):
        """Async: hand `callback` the first line visible in the viewport."""
        if not self._ready:
            callback(1)
            return

        def done(webview, result, _data=None):
            try:
                value = webview.evaluate_javascript_finish(result)
                callback(int(value.to_string()))
            except Exception:
                callback(1)

        self._webview.evaluate_javascript(
            "window.topLine ? window.topLine() : 1", -1, None, None, None, done,
        )

    def get_text(self):
        return self._text_cache

    def set_save_callback(self, callback):
        self._save_callback = callback

    def set_preview_callback(self, callback):
        self._preview_callback = callback

    def set_scroll_callback(self, callback):
        self._scroll_callback = callback

    def set_escape_callback(self, callback):
        self._escape_callback = callback

    def toggle_search(self):
        self._js("toggleSearch()")

    def update_style(self):
        self._apply_style_js()
