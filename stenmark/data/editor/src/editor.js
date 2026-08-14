import {
  EditorView,
  keymap,
  lineNumbers,
  highlightActiveLine,
  drawSelection,
} from "@codemirror/view";
import { EditorState, EditorSelection, Compartment } from "@codemirror/state";
import { markdown } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { history, historyKeymap, defaultKeymap, indentWithTab } from "@codemirror/commands";
import { search, searchKeymap, openSearchPanel, searchPanelOpen } from "@codemirror/search";
import { syntaxHighlighting, defaultHighlightStyle } from "@codemirror/language";
import { oneDark } from "@codemirror/theme-one-dark";
import * as themePackages from "@uiw/codemirror-themes-all";
// The same manifest drives the Preferences combo on the Python side, so the
// key list cannot drift between the two.
import themeManifest from "../themes.json";

const themeCompartment       = new Compartment();
const fontCompartment        = new Compartment();
const lineNumbersCompartment = new Compartment();
const lineWrapCompartment    = new Compartment();
const typewriterCompartment  = new Compartment();

// Adwaita-inspired light theme (custom, matches GTK window)
const adwaitaLight = EditorView.theme(
  {
    "&": { backgroundColor: "transparent", color: "#2e2e2e" },
    ".cm-content": { caretColor: "#2e2e2e" },
    ".cm-gutters": {
      backgroundColor: "rgba(0,0,0,0.04)",
      color: "#999",
      border: "none",
      borderRight: "1px solid rgba(0,0,0,0.08)",
    },
    ".cm-activeLineGutter": { backgroundColor: "rgba(0,0,0,0.06)" },
    ".cm-activeLine": { backgroundColor: "rgba(0,0,0,0.04)" },
    ".cm-focused .cm-selectionBackground, .cm-selectionBackground": {
      backgroundColor: "#c8def5",
    },
    ".cm-cursor": { borderLeftColor: "#2e2e2e" },
    ".cm-panels": {
      backgroundColor: "#efefef",
      borderTop: "1px solid rgba(0,0,0,0.1)",
    },
    ".cm-searchMatch": { backgroundColor: "#ffd700", outline: "none" },
    ".cm-searchMatch.cm-searchMatch-selected": {
      backgroundColor: "#ff8c00",
      color: "#fff",
    },
    ".cm-button": {
      backgroundImage: "none",
      backgroundColor: "#ddd",
      border: "1px solid #bbb",
      borderRadius: "4px",
      color: "#2e2e2e",
    },
    ".cm-textfield": { border: "1px solid #bbb", borderRadius: "4px" },
  },
  { dark: false }
);

// Themes not coming from the theme package: the hand-written Adwaita one that
// matches the GTK window, and One Dark, which ships with CodeMirror itself.
const LOCAL_THEMES = {
  __adwaita_light: [adwaitaLight, syntaxHighlighting(defaultHighlightStyle)],
  __one_dark:      oneDark,
};

const THEMES = {};
for (const entry of themeManifest) {
  if (!entry.export) continue;  // "auto" is resolved per system dark mode
  const ext = LOCAL_THEMES[entry.export] || themePackages[entry.export];
  if (ext) THEMES[entry.key] = ext;
}

// "auto" maps to one of the above based on system dark mode
const AUTO_LIGHT = "adwaita-light";
const AUTO_DARK  = "one-dark";

function resolveTheme(setting, systemDark) {
  if (setting === "auto") return THEMES[systemDark ? AUTO_DARK : AUTO_LIGHT];
  return THEMES[setting] || THEMES[AUTO_LIGHT];
}

// --- Markdown formatting helpers ---

function wrapSelection(marker) {
  return ({ state, dispatch }) => {
    const changes = state.changeByRange((range) => {
      if (range.empty) {
        return {
          changes: [{ from: range.from, insert: marker + marker }],
          range: EditorSelection.cursor(range.from + marker.length),
        };
      }
      const selected = state.sliceDoc(range.from, range.to);
      return {
        changes: [
          { from: range.from, insert: marker },
          { from: range.to, insert: marker },
        ],
        range: EditorSelection.range(
          range.from + marker.length,
          range.to + marker.length
        ),
      };
    });
    dispatch(state.update(changes, { scrollIntoView: true, userEvent: "input" }));
    return true;
  };
}

function insertLink({ state, dispatch }) {
  const range = state.selection.main;
  if (range.empty) {
    dispatch(
      state.update({
        changes: { from: range.from, insert: "[](url)" },
        selection: EditorSelection.cursor(range.from + 1),
        scrollIntoView: true,
      })
    );
  } else {
    const selected = state.sliceDoc(range.from, range.to);
    const insert = `[${selected}](url)`;
    dispatch(
      state.update({
        changes: { from: range.from, to: range.to, insert },
        selection: EditorSelection.range(
          range.from + selected.length + 3,
          range.from + selected.length + 6
        ),
        scrollIntoView: true,
      })
    );
  }
  return true;
}

function insertCodeBlock({ state, dispatch }) {
  const range = state.selection.main;
  if (range.empty) {
    dispatch(
      state.update({
        changes: { from: range.from, insert: "```\n\n```" },
        selection: EditorSelection.cursor(range.from + 4),
        scrollIntoView: true,
      })
    );
  } else {
    const selected = state.sliceDoc(range.from, range.to);
    dispatch(
      state.update({
        changes: {
          from: range.from,
          to: range.to,
          insert: "```\n" + selected + "\n```",
        },
        scrollIntoView: true,
      })
    );
  }
  return true;
}

function prefixLine(prefix) {
  return (view) => {
    const { state } = view;
    const changes = state.changeByRange((range) => {
      const line = state.doc.lineAt(range.from);
      const has = line.text.startsWith(prefix);
      if (has) {
        return {
          changes: { from: line.from, to: line.from + prefix.length, insert: "" },
          range: EditorSelection.range(
            Math.max(range.from - prefix.length, line.from),
            Math.max(range.to - prefix.length, line.from),
          ),
        };
      }
      return {
        changes: { from: line.from, insert: prefix },
        range: EditorSelection.range(
          range.from + prefix.length,
          range.to + prefix.length,
        ),
      };
    });
    view.dispatch(state.update(changes, { scrollIntoView: true, userEvent: "input" }));
    return true;
  };
}

// --- Editor setup ---

// Typewriter mode: the line being written stays put and the document moves
// under it. Two halves — the padding is what lets the last line reach the
// middle at all, since without it the document simply stops at the bottom
// edge and the caret rides down to meet it.
function typewriterExtension() {
  let frame = 0;
  return [
    EditorView.theme({ ".cm-content": { paddingBottom: "50vh" } }),
    EditorView.updateListener.of((update) => {
      // Recentre for edits, and for the caret changing line. Not for moving
      // along a line, and not for plain scrolling: yanking the view back on
      // every keypress in a line, or fighting the wheel, both read as a bug.
      const before = update.startState.doc.lineAt(
        update.startState.selection.main.head
      ).number;
      const after = update.state.doc.lineAt(
        update.state.selection.main.head
      ).number;
      if (!update.docChanged && before === after) return;
      // Dispatching straight from an update listener re-enters the update
      // cycle, so defer a frame; that also collapses a burst into one scroll.
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        centreCaret();
      });
    }),
  ];
}

function centreCaret() {
  view.dispatch({
    effects: EditorView.scrollIntoView(view.state.selection.main.head, {
      y: "center",
    }),
  });
}

const view = new EditorView({
  state: EditorState.create({
    doc: "",
    extensions: [
      history(),
      lineNumbersCompartment.of(lineNumbers()),
      highlightActiveLine(),
      drawSelection(),
      fontCompartment.of([]),
      lineWrapCompartment.of(EditorView.lineWrapping),
      typewriterCompartment.of([]),
      markdown({ codeLanguages: languages }),
      search({ top: true }),
      themeCompartment.of(resolveTheme("auto", false)),
      keymap.of([
        indentWithTab,
        ...defaultKeymap,
        ...historyKeymap,
        ...searchKeymap,
        { key: "Ctrl-b", run: wrapSelection("**") },
        { key: "Ctrl-i", run: wrapSelection("*") },
        { key: "Ctrl-`", run: wrapSelection("`") },
        { key: "Ctrl-k", run: insertLink },
        { key: "Ctrl-Shift-x", run: wrapSelection("~~") },
        { key: "Ctrl-Shift-k", run: insertCodeBlock },
        { key: "Ctrl-Shift-u", run: prefixLine("- ") },
        { key: "Ctrl-Shift-o", run: prefixLine("1. ") },
        {
          key: "Ctrl-s",
          run: (v) => {
            window.webkit.messageHandlers.textChanged.postMessage(
              v.state.doc.toString()
            );
            window.webkit.messageHandlers.saveRequest.postMessage("");
            return true;
          },
          preventDefault: true,
        },
        {
          key: "Ctrl-f",
          run: (v) => { openSearchPanel(v); return true; },
          preventDefault: true,
        },
        {
          // Leave edit mode — but only once Escape has nothing left to
          // dismiss inside the editor itself.
          key: "Escape",
          run: (v) => {
            if (searchPanelOpen(v.state)) return false;
            // Guarded: an upgrade under a running app can pair this bundle
            // with a Python side that has no escapeRequest handler. Better
            // that Escape does nothing than that it throws mid-keymap.
            const mh = window.webkit && window.webkit.messageHandlers;
            if (!mh || !mh.escapeRequest) return false;
            mh.textChanged.postMessage(v.state.doc.toString());
            mh.escapeRequest.postMessage("");
            return true;
          },
        },
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          window.webkit.messageHandlers.textChanged.postMessage(
            update.state.doc.toString()
          );
        }
      }),
    ],
  }),
  parent: document.getElementById("editor"),
});

// --- Python-callable API ---

window.setContent = (text) => {
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: text },
    selection: EditorSelection.cursor(0),
    scrollIntoView: true,
  });
  view.focus();
};

window.setTheme = (setting, systemDark) => {
  view.dispatch({
    effects: themeCompartment.reconfigure(resolveTheme(setting, systemDark)),
  });
};

window.setFont = (family, size) => {
  view.dispatch({
    effects: fontCompartment.reconfigure(
      EditorView.theme({
        "&": { fontSize: size + "pt" },
        ".cm-content, .cm-gutters": { fontFamily: family + ", monospace" },
      })
    ),
  });
};

window.setLineNumbers = (show) => {
  view.dispatch({
    effects: lineNumbersCompartment.reconfigure(show ? lineNumbers() : []),
  });
};

window.setLineWrap = (wrap) => {
  view.dispatch({
    effects: lineWrapCompartment.reconfigure(wrap ? EditorView.lineWrapping : []),
  });
};

window.setTypewriter = (on) => {
  view.dispatch({
    effects: typewriterCompartment.reconfigure(on ? typewriterExtension() : []),
  });
  // Switching it on should take effect where the caret already is, rather
  // than waiting for the next keystroke.
  if (on) centreCaret();
};

window.toggleSearch = () => {
  openSearchPanel(view);
};

window.focusEditor = () => {
  view.focus();
};

window.scrollToLine = (lineNum) => {
  const line = view.state.doc.line(Math.min(lineNum, view.state.doc.lines));
  view.dispatch({
    selection: EditorSelection.cursor(line.from),
    scrollIntoView: true,
  });
  view.focus();
};

// Place the caret at `word` within the block starting at `lineNum` — the
// hand-off from the rendered view, which only knows block-level source lines.
window.gotoLine = (lineNum, word, center) => {
  const doc = view.state.doc;
  const line = doc.line(Math.max(1, Math.min(lineNum || 1, doc.lines)));
  let pos = line.from;
  if (word) {
    // A block may wrap over several source lines; search a little beyond it
    const end = Math.min(doc.length, line.from + 4000);
    const idx = doc.sliceString(line.from, end).indexOf(word);
    if (idx >= 0) pos = line.from + idx;
  }
  view.dispatch({
    selection: EditorSelection.cursor(pos),
    effects: EditorView.scrollIntoView(pos, {
      y: center ? "center" : "start",
      yMargin: center ? 0 : 8,
    }),
  });
  view.focus();
};

// First line still visible at the top of the viewport
window.topLine = () => {
  try {
    const rect = view.scrollDOM.getBoundingClientRect();
    const pos = view.posAtCoords({ x: rect.left + 1, y: rect.top + 1 }, false);
    if (pos != null) return view.state.doc.lineAt(pos).number;
  } catch (e) {}
  return 1;
};

// --- Toolbar API ---

window.insertText = (text) => {
  view.dispatch(view.state.replaceSelection(text));
};

window.formatBold      = () => wrapSelection("**")(view);
window.formatItalic    = () => wrapSelection("*")(view);
window.formatStrike    = () => wrapSelection("~~")(view);
window.formatCode      = () => wrapSelection("`")(view);
window.formatLink      = () => insertLink(view);
window.formatCodeBlock = () => insertCodeBlock(view);
window.formatHeading   = (n) => prefixLine("#".repeat(n) + " ")(view);
window.formatBullet    = () => prefixLine("- ")(view);
window.formatNumbered  = () => prefixLine("1. ")(view);
window.formatQuote     = () => prefixLine("> ")(view);

// --- Scroll sync (editor -> preview) ---

let _scrollTimer = null;
view.scrollDOM.addEventListener("scroll", () => {
  if (window._scrollSyncEnabled === false) return;
  if (_scrollTimer) return;
  _scrollTimer = setTimeout(() => {
    _scrollTimer = null;
    try {
      const rect = view.scrollDOM.getBoundingClientRect();
      const topPos = view.posAtCoords({ x: rect.left + 1, y: rect.top + 1 });
      if (topPos != null) {
        const line = view.state.doc.lineAt(topPos).number;
        if (window.webkit && window.webkit.messageHandlers.scrollLine) {
          window.webkit.messageHandlers.scrollLine.postMessage(String(line));
        }
      }
    } catch (e) {}
  }, 80);
});

view.focus();
