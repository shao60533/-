#!/usr/bin/env node
/**
 * v2.1 frontend guard — no user-visible "快速" analysis mode.
 *
 * The ladder collapsed from {quick, standard, deep} to {standard, deep};
 * "快速" must not appear in any JSX text node. Comments / type
 * unions / legacy field signatures may still mention quick (DB rows
 * still carry it), so this guard is a heuristic that flags lines we
 * believe end up rendered to users:
 *
 *   - JSX text content like ``>快速<`` or ``>...快速...<``
 *   - JSX attribute values like ``label="快速"`` / ``placeholder="快速"``
 *   - String literals passed to ``{... "快速" ...}`` JSX expressions
 *     in islands/ files (most user-visible surface)
 *
 * Runs from repo root via ``npm test``. Exits non-zero on a hit so
 * CI / a future Playwright suite has an easy gate.
 *
 * Why no vitest: this branch's vitest infra was rolled back in a prior
 * release. Re-introducing it would mean a large devDep install for
 * the smallest possible value (one regression check). A pure-Node
 * static grep covers exactly the regression the user reported
 * ("frontend still showed 快速 radio after backend rename") and
 * stays maintainable.
 */
import { promises as fs } from "node:fs"
import path from "node:path"
import process from "node:process"

const SRC = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  "..", "..", "src",
)
const NEEDLE = "快速"

// JSX-text-context markers. We want to flag ``>快速<``, ``"快速"`` in
// JSX attributes, and template-string usage. We'll only flag a line
// when it contains one of these patterns; bare line comments stay
// allowed so the legacy ``case "quick": return "标准"`` mapping
// docstring / inline comment can keep the historical context.
const PATTERNS = [
  />\s*[^<]*快速[^<]*</,            // JSX text node like  ``>快速</span>``
  /\b(label|placeholder|hint|title|aria-label)\s*[:=]\s*["'`][^"'`]*快速/,
  /\b(label|placeholder|hint|title)\s*:\s*["'`][^"'`]*快速/,
]

async function* walk(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true })
  for (const e of entries) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) {
      // Skip generated / vendor dirs.
      if (e.name === "node_modules" || e.name.startsWith(".")) continue
      yield* walk(p)
    } else if (
      e.name.endsWith(".tsx") || e.name.endsWith(".ts")
        || e.name.endsWith(".jsx") || e.name.endsWith(".js")
    ) {
      yield p
    }
  }
}

function isCommentLine(line) {
  const trimmed = line.trim()
  return trimmed.startsWith("//")
    || trimmed.startsWith("*")
    || trimmed.startsWith("/*")
    || trimmed.startsWith("*/")
}

const hits = []
for await (const file of walk(SRC)) {
  const text = await fs.readFile(file, "utf-8")
  if (!text.includes(NEEDLE)) continue
  const lines = text.split("\n")
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (!line.includes(NEEDLE)) continue
    if (isCommentLine(line)) continue
    if (!PATTERNS.some((re) => re.test(line))) continue
    hits.push({ file: path.relative(SRC, file), line: i + 1, text: line.trim() })
  }
}

if (hits.length === 0) {
  console.log("[no-quick-mode] OK — no user-visible \"快速\" mode literal in src/")
  process.exit(0)
}

console.error(
  `[no-quick-mode] FAIL — found ${hits.length} hits of user-visible "快速" literal:\n`,
)
for (const h of hits) {
  console.error(`  ${h.file}:${h.line}  ${h.text}`)
}
console.error(
  "\nv2.1 collapsed the depth ladder to {standard, deep}; 快速 must "
    + "not appear in JSX text/attributes. If this is intentionally a "
    + "comment/legacy-field, move it to a // line — the guard ignores "
    + "comment-only lines.",
)
process.exit(1)
