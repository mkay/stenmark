/**
 * Regenerates ../themes.json from @uiw/codemirror-themes-all.
 *
 *   npm run themes
 *
 * themes.json is the single source of truth for the editor's theme list:
 * editor.js builds its theme map from it and Stenmark's Preferences dialog
 * reads the same file for the picker. Run this after bumping the theme
 * package, then review `git diff themes.json` — new themes show up there with
 * a label derived from their export name, which is right often enough to be
 * useful and wrong often enough to be worth reading ("Github Light" wants to
 * be "GitHub Light").
 *
 * Existing labels are preserved, so hand-corrections survive regeneration, as
 * are hand-written "family"/"variant" pairings — the suffix rule catches
 * github-light/github-dark but not tokyo-night/tokyo-night-day.
 *
 * Entries whose export is null or starts with "__" are kept verbatim: those
 * are Auto and the two themes that do not come from the package (the
 * hand-written Adwaita Light and CodeMirror's own One Dark).
 *
 * Lives in src/ because meson excludes that directory from the installed
 * package — nothing here ships to users.
 */
import { readFileSync, writeFileSync } from "node:fs";
import * as themePackages from "@uiw/codemirror-themes-all";

const MANIFEST = new URL("../themes.json", import.meta.url);
const COLOR_FIELDS = [
  "background", "foreground", "caret",
  "selection", "gutterBackground", "lineHighlight",
];

/** Relative luminance, or null if the colour is not a plain hex value. */
function luminance(value) {
  let hex = String(value || "").trim().replace(/^#/, "");
  if (hex.length === 3) hex = [...hex].map((c) => c + c).join("");
  if (!/^[0-9a-f]{6}$/i.test(hex)) return null;
  const n = parseInt(hex, 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

const kebab = (name) => name.replace(/(?<!^)(?=[A-Z])/g, "-").toLowerCase();

const deriveLabel = (name) =>
  name
    .replace(/(?<!^)(?=[A-Z])/g, " ")
    .replace(/^./, (c) => c.toUpperCase());

/** Theme extensions, as opposed to the settings objects and style arrays. */
function isThemeExtension(value) {
  if (value && typeof value === "object" && "extension" in value) return true;
  if (!Array.isArray(value)) return false;
  // a *Style export is an array of { tag, ... } highlight specs
  return !(value[0] && typeof value[0] === "object" && "tag" in value[0]);
}

/** Light/dark counterpart, from the key suffix. Hand-written pairings win. */
function derivePair(key) {
  for (const [suffix, variant] of [["-light", "light"], ["-dark", "dark"]]) {
    if (key.endsWith(suffix)) return { family: key.slice(0, -suffix.length), variant };
  }
  return null;
}

const previous = JSON.parse(readFileSync(MANIFEST, "utf8"));
const labelFor = new Map(
  previous.filter((e) => e.export).map((e) => [e.export, e.label])
);
const pairFor = new Map(
  previous.filter((e) => e.export && e.family).map((e) => [e.export, e])
);
const kept = previous.filter((e) => !e.export || e.export.startsWith("__"));

const added = [];
const generated = [];

for (const name of Object.keys(themePackages)) {
  if (/^defaultSettings/.test(name) || /Style$/.test(name) || /Init$/.test(name)) continue;
  if (!isThemeExtension(themePackages[name])) continue;

  const settings = themePackages["defaultSettings" + name[0].toUpperCase() + name.slice(1)];
  if (!settings) {
    console.warn(`! ${name}: no defaultSettings export, skipped`);
    continue;
  }

  const colors = Object.fromEntries(
    COLOR_FIELDS.filter((f) => settings[f]).map((f) => [f, settings[f]])
  );
  const lum = luminance(settings.background);
  if (lum === null) {
    console.warn(`! ${name}: background ${settings.background} is not plain hex, assuming light`);
  }

  let label = labelFor.get(name);
  if (label === undefined) {
    label = deriveLabel(name);
    added.push(`${name} -> "${label}"`);
  }

  const key = kebab(name);
  const hand = pairFor.get(name);
  const pair = hand ? { family: hand.family, variant: hand.variant } : derivePair(key);
  generated.push({ key, export: name, label, dark: (lum ?? 1) < 0.5, ...pair, colors });
}

generated.sort((a, b) => a.export.toLowerCase().localeCompare(b.export.toLowerCase()));

const entries = [...kept, ...generated];

const keys = entries.map((e) => e.key);
const duplicates = keys.filter((k, i) => keys.indexOf(k) !== i);
if (duplicates.length) {
  console.error(`duplicate keys: ${duplicates.join(", ")}`);
  process.exit(1);
}

// A family with only one variant cannot answer "match light/dark" — drop it,
// so the switch in Preferences is never offered against a missing counterpart.
const variantsPerFamily = new Map();
for (const e of entries) {
  if (!e.family) continue;
  const seen = variantsPerFamily.get(e.family) || new Set();
  seen.add(e.variant);
  variantsPerFamily.set(e.family, seen);
}
for (const e of entries) {
  if (e.family && variantsPerFamily.get(e.family).size < 2) {
    console.warn(`! ${e.key}: family "${e.family}" has no ${e.variant === "dark" ? "light" : "dark"} counterpart, unpaired`);
    delete e.family;
    delete e.variant;
  }
}

// Keys are what settings.json stores — losing one silently resets a user's theme
const dropped = previous.map((e) => e.key).filter((k) => !keys.includes(k));
if (dropped.length) {
  console.error(`keys that would disappear: ${dropped.join(", ")}`);
  console.error("A stored setting pointing at one of these would fall back to Adwaita Light.");
  process.exit(1);
}

writeFileSync(MANIFEST, JSON.stringify(entries, null, 2) + "\n");

console.log(`${entries.length} entries written (${generated.length} from the package)`);
if (added.length) {
  console.log(`\n${added.length} new theme(s) — check the derived labels:`);
  for (const line of added) console.log(`  ${line}`);
}
