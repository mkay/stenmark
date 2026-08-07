# SPDX-FileCopyrightText: 2026 Kreuder <mk@singular.de>
# SPDX-License-Identifier: GPL-3.0-or-later

import json

from pygments.formatters import HtmlFormatter

from stenmark.i18n import _


# Each theme dict defines the visual palette and the Pygments style for code blocks.
_THEMES = {
    "light": {
        "bg": "#ffffff", "fg": "#1a1a1a", "link": "#0366d6",
        "code_bg": "#f5f5f5", "border": "#ddd",
        "heading_border": "#ddd", "blockquote_border": "#ddd",
        "blockquote_fg": "#666", "table_th_bg": "#f5f5f5",
        "table_border": "#ddd", "hr_color": "#ddd",
        "pygments": "default",
    },
    "dark": {
        "bg": "#242424", "fg": "#e0e0e0", "link": "#6ea8fe",
        "code_bg": "#363636", "border": "#555",
        "heading_border": "#444", "blockquote_border": "#555",
        "blockquote_fg": "#aaa", "table_th_bg": "#363636",
        "table_border": "#444", "hr_color": "#444",
        "pygments": "monokai",
    },
    "github": {
        "bg": "#ffffff", "fg": "#24292f", "link": "#0969da",
        "code_bg": "#f6f8fa", "border": "#d0d7de",
        "heading_border": "#d0d7de", "blockquote_border": "#d0d7de",
        "blockquote_fg": "#57606a", "table_th_bg": "#f6f8fa",
        "table_border": "#d0d7de", "hr_color": "#d0d7de",
        "pygments": "friendly",
    },
    "github-dark": {
        "bg": "#0d1117", "fg": "#c9d1d9", "link": "#58a6ff",
        "code_bg": "#161b22", "border": "#30363d",
        "heading_border": "#21262d", "blockquote_border": "#3b434b",
        "blockquote_fg": "#8b949e", "table_th_bg": "#161b22",
        "table_border": "#30363d", "hr_color": "#21262d",
        "pygments": "github-dark",
    },
    "sepia": {
        "bg": "#f8f0e3", "fg": "#3c3836", "link": "#8f3f71",
        "code_bg": "#ede8d8", "border": "#c4b89a",
        "heading_border": "#c4b89a", "blockquote_border": "#c4b89a",
        "blockquote_fg": "#7c6f64", "table_th_bg": "#ede8d8",
        "table_border": "#c4b89a", "hr_color": "#c4b89a",
        "pygments": "friendly",
    },
    "solarized-light": {
        "bg": "#fdf6e3", "fg": "#657b83", "link": "#268bd2",
        "code_bg": "#eee8d5", "border": "#93a1a1",
        "heading_border": "#93a1a1", "blockquote_border": "#93a1a1",
        "blockquote_fg": "#839496", "table_th_bg": "#eee8d5",
        "table_border": "#93a1a1", "hr_color": "#93a1a1",
        "pygments": "solarized-light",
    },
    "solarized-dark": {
        "bg": "#002b36", "fg": "#839496", "link": "#268bd2",
        "code_bg": "#073642", "border": "#586e75",
        "heading_border": "#586e75", "blockquote_border": "#586e75",
        "blockquote_fg": "#657b83", "table_th_bg": "#073642",
        "table_border": "#586e75", "hr_color": "#586e75",
        "pygments": "solarized-dark",
    },
}

# Fallbacks if a Pygments style name isn't installed
_PYGMENTS_FALLBACKS = {
    "github-dark": "monokai",
    "solarized-light": "default",
    "solarized-dark": "monokai",
}


def _pygments_css(style_name):
    try:
        return HtmlFormatter(style=style_name).get_style_defs(".highlight")
    except Exception:
        fallback = _PYGMENTS_FALLBACKS.get(style_name, "default")
        return HtmlFormatter(style=fallback).get_style_defs(".highlight")


def wrap_html(body_html, font_family="Sans", font_size=16, dark=False, viewer_theme="auto"):
    if viewer_theme == "auto":
        t = _THEMES["dark" if dark else "light"]
    else:
        t = _THEMES.get(viewer_theme, _THEMES["light"])

    pygments_css = _pygments_css(t["pygments"])

    # Interpolated rather than written inline: the template is one big
    # f-string, and xgettext cannot see a string it never parses as Python.
    # json.dumps() and slice off its quotes — a translation containing an
    # apostrophe or quote mark must not break out of the JS string literal.
    copy_code_label = json.dumps(_("Copy code"))[1:-1]
    copied_label = json.dumps(_("Copied!"))[1:-1]

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    font-family: {font_family}, sans-serif;
    font-size: {font_size}px;
    line-height: 1.6;
    color: {t['fg']};
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
    background: {t['bg']};
}}
h1, h2, h3, h4, h5, h6 {{
    margin-top: 1.2em;
    margin-bottom: 0.4em;
    line-height: 1.3;
}}
h1 {{ font-size: 1.8em; border-bottom: 1px solid {t['heading_border']}; padding-bottom: 0.2em; }}
h2 {{ font-size: 1.5em; border-bottom: 1px solid {t['heading_border']}; padding-bottom: 0.2em; }}
h3 {{ font-size: 1.25em; }}
a {{ color: {t['link']}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code {{
    font-family: monospace;
    background: {t['code_bg']};
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.9em;
}}
pre {{
    position: relative;
    background: {t['code_bg']};
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
    line-height: 1.4;
    white-space: pre;
}}
.copy-btn {{
    position: absolute;
    top: 6px;
    right: 6px;
    background: none;
    border: 1px solid {t['border']};
    border-radius: 4px;
    cursor: pointer;
    padding: 4px;
    opacity: 0;
    transition: opacity 0.15s;
    display: flex;
    align-items: center;
    justify-content: center;
    color: {t['fg']};
}}
pre:hover .copy-btn {{ opacity: 0.7; }}
.copy-btn:hover {{ opacity: 1 !important; background: {t['code_bg']}; }}
.copy-btn:active {{ transform: scale(0.95); }}
.copy-btn.copied {{ opacity: 1; }}
pre code {{
    background: none;
    padding: 0;
}}
blockquote {{
    margin: 0.8em 0;
    padding: 0.4em 1em;
    border-left: 4px solid {t['blockquote_border']};
    color: {t['blockquote_fg']};
}}
table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}}
table th, table td {{
    border: 1px solid {t['table_border']};
    padding: 8px 12px;
    text-align: left;
}}
table th {{
    background: {t['table_th_bg']};
    font-weight: 600;
}}
img {{
    max-width: 100%;
    height: auto;
}}
hr {{
    border: none;
    border-top: 1px solid {t['hr_color']};
    margin: 1.5em 0;
}}
ul, ol {{
    padding-left: 1.5em;
}}
li {{ margin: 0.3em 0; }}
li.task-item {{
    list-style: none;
    margin-left: -1.2em;
}}
li.task-item input[type="checkbox"] {{
    cursor: pointer;
    width: 1em;
    height: 1em;
    margin-right: 0.4em;
    vertical-align: -0.1em;
    accent-color: {t['link']};
}}
{pygments_css}
/* WebKit find-in-page highlight overrides */
::highlight(search) {{ background-color: #ffdd00 !important; color: #000 !important; }}
::highlight(current) {{ background-color: #ff6a00 !important; color: #fff !important; }}
</style>
</head>
<body>
{body_html}
<script>
document.addEventListener("DOMContentLoaded", function() {{
    document.querySelectorAll("li.task-item input[type='checkbox']").forEach(function(cb, i) {{
        cb.addEventListener("change", function() {{
            window.webkit.messageHandlers.checkboxToggled.postMessage(
                JSON.stringify({{index: i, checked: cb.checked}})
            );
        }});
    }});
    var svgIcon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    document.querySelectorAll("pre").forEach(function(pre) {{
        var btn = document.createElement("button");
        btn.className = "copy-btn";
        btn.title = "{copy_code_label}";
        btn.innerHTML = svgIcon;
        btn.addEventListener("click", function() {{
            var code = pre.querySelector("code");
            var raw = (code || pre).textContent;
            var text = raw.split("\\n").filter(function(line) {{
                var t = line.trim();
                return t !== "" && !t.startsWith("#");
            }}).join("\\n");
            window.webkit.messageHandlers.copyCode.postMessage(text);
            btn.innerHTML = "{copied_label}";
            btn.classList.add("copied");
            setTimeout(function() {{
                btn.innerHTML = svgIcon;
                btn.classList.remove("copied");
            }}, 1500);
        }});
        pre.appendChild(btn);
    }});
}});
window.scrollToSourceLine = function(line) {{
    // Find the element with the closest data-source-line <= line
    var els = document.querySelectorAll("[data-source-line]");
    if (!els.length) return;
    var best = els[0];
    for (var i = 0; i < els.length; i++) {{
        var n = parseInt(els[i].getAttribute("data-source-line"), 10);
        if (n <= line) best = els[i];
        else break;
    }}
    best.scrollIntoView({{ behavior: "smooth", block: "start" }});
}};
</script>
</body>
</html>"""
