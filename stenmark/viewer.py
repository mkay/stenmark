import json
import os
import re

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, WebKit

from stenmark.i18n import _

from stenmark.markdown_renderer import MarkdownRenderer
from stenmark.html_template import wrap_html


class MarkdownViewer(Gtk.Box):
    __gsignals__ = {
        "link-activated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "navigate-back": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "navigate-forward": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._settings = settings
        self._renderer = MarkdownRenderer()
        self._current_path = None
        self._can_go_back = False
        self._can_go_forward = False

        self._skip_next_load = False

        ucm = WebKit.UserContentManager()
        ucm.register_script_message_handler("copyCode")
        ucm.connect("script-message-received::copyCode", self._on_copy_code)
        ucm.register_script_message_handler("checkboxToggled")
        ucm.connect("script-message-received::checkboxToggled", self._on_checkbox_toggled)

        # Custom find highlight styles (JS-driven, not FindController)
        find_css = WebKit.UserStyleSheet(
            "mark.sf-match {"
            "  background: rgba(255, 221, 0, 0.5);"
            "  color: inherit;"
            "  border-radius: 2px;"
            "}"
            "mark.sf-current {"
            "  background: rgba(255, 106, 0, 0.35);"
            "  color: inherit;"
            "  border-radius: 2px;"
            "}",
            WebKit.UserContentInjectedFrames.ALL_FRAMES,
            WebKit.UserStyleLevel.USER,
            None,
            None,
        )
        ucm.add_style_sheet(find_css)

        self._webview = WebKit.WebView(user_content_manager=ucm)
        self._webview.set_vexpand(True)
        self._webview.set_hexpand(True)
        self._webview.connect("decide-policy", self._on_decide_policy)
        self._webview.connect("context-menu", self._on_context_menu)

        ws = self._webview.get_settings()
        ws.set_enable_developer_extras(False)

        self.append(self._webview)
        self._build_search_bar()
        self._show_empty()

    def _build_search_bar(self):
        self._find_match_count = 0
        self._find_current = -1

        box = Gtk.Box(spacing=4)
        box.add_css_class("toolbar")
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        self._search_entry = Gtk.SearchEntry(hexpand=True, placeholder_text=_("Find in document"))
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("activate", lambda *_: self._find_next())
        box.append(self._search_entry)

        self._match_label = Gtk.Label(css_classes=["dim-label", "caption"])
        self._match_label.set_visible(False)
        box.append(self._match_label)

        prev_btn = Gtk.Button(icon_name="stenmark-go-up-symbolic", tooltip_text=_("Previous match"))
        prev_btn.connect("clicked", lambda *_: self._find_prev())
        box.append(prev_btn)

        next_btn = Gtk.Button(icon_name="stenmark-go-down-symbolic", tooltip_text=_("Next match"))
        next_btn.connect("clicked", lambda *_: self._find_next())
        box.append(next_btn)

        close_btn = Gtk.Button(icon_name="stenmark-close-symbolic", tooltip_text=_("Close"))
        close_btn.connect("clicked", lambda *_: self.hide_search())
        box.append(close_btn)

        self._search_bar = box
        self._search_bar.set_visible(False)
        self.prepend(self._search_bar)

        key_ctl = Gtk.EventControllerKey()
        key_ctl.connect("key-pressed", self._on_search_key)
        self._search_entry.add_controller(key_ctl)

    # ---- JS-driven find-in-page -----------------------------------------

    _FIND_JS = """
    (function() {
      // Remove previous marks
      document.querySelectorAll('mark.sf-match, mark.sf-current').forEach(m => {
        const parent = m.parentNode;
        while (m.firstChild) parent.insertBefore(m.firstChild, m);
        parent.removeChild(m);
        parent.normalize();
      });

      const query = %s;
      if (!query) return JSON.stringify({count: 0, current: -1});

      const marks = [];
      const walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_TEXT, null
      );
      const ranges = [];
      const lower = query.toLowerCase();
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const text = node.textContent.toLowerCase();
        let start = 0;
        while (true) {
          const idx = text.indexOf(lower, start);
          if (idx === -1) break;
          ranges.push({node, start: idx, end: idx + query.length});
          start = idx + 1;
        }
      }

      // Wrap in reverse order to preserve offsets
      for (let i = ranges.length - 1; i >= 0; i--) {
        const r = ranges[i];
        const range = document.createRange();
        range.setStart(r.node, r.start);
        range.setEnd(r.node, r.end);
        const mark = document.createElement('mark');
        mark.className = 'sf-match';
        range.surroundContents(mark);
      }

      const allMarks = document.querySelectorAll('mark.sf-match');
      if (allMarks.length > 0) {
        allMarks[0].classList.add('sf-current');
        allMarks[0].scrollIntoView({block: 'center'});
      }
      return JSON.stringify({count: allMarks.length, current: allMarks.length > 0 ? 0 : -1});
    })()
    """

    _NAV_JS = """
    (function() {
      const marks = document.querySelectorAll('mark.sf-match');
      if (marks.length === 0) return JSON.stringify({count: 0, current: -1});
      marks.forEach(m => m.classList.remove('sf-current'));
      const idx = %d;
      marks[idx].classList.add('sf-current');
      marks[idx].scrollIntoView({block: 'center'});
      return JSON.stringify({count: marks.length, current: idx});
    })()
    """

    _CLEAR_JS = """
    (function() {
      document.querySelectorAll('mark.sf-match, mark.sf-current').forEach(m => {
        const parent = m.parentNode;
        while (m.firstChild) parent.insertBefore(m.firstChild, m);
        parent.removeChild(m);
        parent.normalize();
      });
    })()
    """

    def _js(self, script, callback=None):
        self._webview.evaluate_javascript(script, -1, None, None, None,
                                          callback or (lambda *_: None))

    def _on_search_changed(self, entry):
        text = entry.get_text()
        if text:
            escaped = json.dumps(text)
            self._js(self._FIND_JS % escaped, self._on_find_result)
        else:
            self._js(self._CLEAR_JS)
            self._find_match_count = 0
            self._find_current = -1
            self._match_label.set_visible(False)

    def _on_find_result(self, webview, result):
        try:
            val = webview.evaluate_javascript_finish(result)
            data = json.loads(val.to_string())
            self._find_match_count = data["count"]
            self._find_current = data["current"]
        except Exception:
            self._find_match_count = 0
            self._find_current = -1
        self._update_match_label()

    def _find_next(self):
        if self._find_match_count == 0:
            return
        self._find_current = (self._find_current + 1) % self._find_match_count
        self._js(self._NAV_JS % self._find_current, self._on_find_result)

    def _find_prev(self):
        if self._find_match_count == 0:
            return
        self._find_current = (self._find_current - 1) % self._find_match_count
        self._js(self._NAV_JS % self._find_current, self._on_find_result)

    def _update_match_label(self):
        if self._find_match_count > 0:
            self._match_label.set_label(
                f"{self._find_current + 1}/{self._find_match_count}"
            )
            self._match_label.set_visible(True)
        else:
            self._match_label.set_label(_("No matches"))
            self._match_label.set_visible(bool(self._search_entry.get_text()))

    def _on_search_key(self, _ctl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.hide_search()
            return True
        return False

    def toggle_search(self):
        if self._search_bar.get_visible():
            self.hide_search()
        else:
            self._search_bar.set_visible(True)
            self._search_entry.grab_focus()

    def hide_search(self):
        self._search_bar.set_visible(False)
        self._search_entry.set_text("")
        self._js(self._CLEAR_JS)
        self._find_match_count = 0
        self._find_current = -1
        self._match_label.set_visible(False)

    def _on_checkbox_toggled(self, _ucm, result):
        try:
            data = json.loads(result.to_string())
            index = data["index"]
            checked = data["checked"]
        except Exception:
            return
        if not self._current_path:
            return
        try:
            with open(self._current_path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return
        pattern = re.compile(r'^(\s*[-*+]\s+)\[[ xX]\]', re.MULTILINE)
        matches = list(pattern.finditer(text))
        if index >= len(matches):
            return
        m = matches[index]
        mark = "x" if checked else " "
        bracket_pos = m.end(1) + 1  # position of the space or 'x' inside [...]
        new_text = text[:bracket_pos] + mark + text[bracket_pos + 1:]
        try:
            with open(self._current_path, "w", encoding="utf-8") as f:
                f.write(new_text)
        except OSError:
            return
        self._skip_next_load = True

    def _on_copy_code(self, _ucm, result):
        text = result.to_string()
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)

    def _on_decide_policy(self, _webview, decision, decision_type):
        if decision_type != WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            return False

        action = decision.get_navigation_action()
        if action.get_navigation_type() != WebKit.NavigationType.LINK_CLICKED:
            return False

        request = action.get_request()
        uri = request.get_uri()

        # External links → open in default browser
        if uri.startswith("http://") or uri.startswith("https://"):
            decision.ignore()
            Gio.AppInfo.launch_default_for_uri(uri, None)
            return True

        # Local file links
        if uri.startswith("file://"):
            from urllib.parse import unquote, urlparse
            parsed = urlparse(uri)
            path = unquote(parsed.path)

            if path.lower().endswith(".md"):
                decision.ignore()
                if os.path.isfile(path):
                    self.emit("link-activated", path)
                return True

        # Block all other navigation (don't leave the rendered page)
        decision.ignore()
        return True

    def set_nav_state(self, can_back, can_forward):
        self._can_go_back = can_back
        self._can_go_forward = can_forward

    def _on_context_menu(self, _webview, menu, _hit_result):
        # Remove WebKit's built-in navigation items (Back, Forward, Stop, Reload)
        # which don't work with load_html()
        _remove = {
            WebKit.ContextMenuAction.GO_BACK,
            WebKit.ContextMenuAction.GO_FORWARD,
            WebKit.ContextMenuAction.STOP,
            WebKit.ContextMenuAction.RELOAD,
        }
        for item in list(menu.get_items()):
            if item.get_stock_action() in _remove:
                menu.remove(item)

        # Add our own Back / Forward at the top
        back_action = Gio.SimpleAction.new("ctx-back", None)
        back_action.set_enabled(self._can_go_back)
        back_action.connect("activate", lambda *_: self.emit("navigate-back"))

        fwd_action = Gio.SimpleAction.new("ctx-forward", None)
        fwd_action.set_enabled(self._can_go_forward)
        fwd_action.connect("activate", lambda *_: self.emit("navigate-forward"))

        back_item = WebKit.ContextMenuItem.new_from_gaction(back_action, _("Back"), None)
        fwd_item = WebKit.ContextMenuItem.new_from_gaction(fwd_action, _("Forward"), None)

        menu.prepend(WebKit.ContextMenuItem.new_separator())
        menu.prepend(fwd_item)
        menu.prepend(back_item)
        return False

    def _is_dark(self):
        style = Adw.StyleManager.get_default()
        return style.get_dark()

    def _show_empty(self):
        html = wrap_html(
            "<p style='color:#888; text-align:center; margin-top:40vh;'>"
            + GLib.markup_escape_text(_("Select a markdown file to view"))
            + "</p>",
            self._settings.font_family,
            self._settings.font_size,
            dark=self._is_dark(),
            viewer_theme=self._settings.viewer_theme,
        )
        self._webview.load_html(html, "file:///")

    def load_file(self, path):
        if self._skip_next_load and path == self._current_path:
            self._skip_next_load = False
            return
        self._skip_next_load = False
        self._current_path = path
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            self._show_empty()
            return
        self.render_text(text, path)

    def render_text(self, text, path=None):
        if path:
            self._current_path = path
        body = self._renderer.render(text)
        html = wrap_html(body, self._settings.font_family, self._settings.font_size,
                         dark=self._is_dark(), viewer_theme=self._settings.viewer_theme)
        base_uri = "file://"
        if self._current_path:
            base_uri = "file://" + os.path.dirname(os.path.abspath(self._current_path)) + "/"
        self._webview.load_html(html, base_uri)

    def reload(self):
        if self._current_path:
            self.load_file(self._current_path)

    def print_pdf(self, parent):
        op = WebKit.PrintOperation.new(self._webview)
        op.run_dialog(parent)

    def scroll_to_line(self, line):
        self._webview.evaluate_javascript(
            f"window.scrollToSourceLine && window.scrollToSourceLine({line})",
            -1, None, None, None, None,
        )

    def update_style(self):
        if self._current_path:
            self.reload()
