#!/usr/bin/env node
//
// Soft/hard line-count caps per code area. Counts non-blank, non-comment lines.
// - `--staged` checks only staged files (pre-commit, fast).
// - `--all`    checks every tracked file (pre-push, slower).
//
// Escape hatch: first line of the file = `// lint-file-size: <reason>`
// (Python / shell: `# lint-file-size: <reason>`). Use sparingly; oversized files
// usually want splitting, not annotating.

const { execFileSync } = require("node:child_process");
const { existsSync, readFileSync } = require("node:fs");
const path = require("node:path");

const args = new Set(process.argv.slice(2));
const mode = args.has("--all") ? "all" : args.has("--staged") ? "staged" : "all";

const CODE_EXTENSIONS = new Set([
  ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
  ".go", ".py", ".sql", ".sh",
]);

function git(argv) {
  return execFileSync("git", argv, { encoding: "utf8" }).trim();
}

function listFiles() {
  if (mode === "staged") {
    const out = git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]);
    return out ? out.split("\n") : [];
  }
  const out = git(["ls-files"]);
  return out ? out.split("\n") : [];
}

function normalize(p) {
  return p.split(path.sep).join("/");
}

function isCodeFile(p) {
  return CODE_EXTENSIONS.has(path.extname(p));
}

function isExempt(file) {
  const f = normalize(file);
  const base = path.basename(f);
  return (
    f.endsWith(".md") ||
    f.includes("/node_modules/") ||
    f.includes("/.next/") ||
    f.includes("/__pycache__/") ||
    f.includes("/.venv/") ||
    f.includes("/dist/") ||
    // Migrations are intentionally append-only; keep them out of the cap.
    (f.startsWith("infra/migrations/") && f.endsWith(".sql")) ||
    // sqlc-generated code (when we eventually run sqlc).
    f.startsWith("apps/api/internal/database/db/") ||
    // Auto-generated Next.js types.
    f.endsWith(".d.ts") ||
    f.endsWith(".gen.ts") ||
    f.endsWith(".generated.ts") ||
    base === "next-env.d.ts" ||
    base.includes(".config.")
  );
}

function ruleFor(file) {
  const f = normalize(file);
  const base = path.basename(f);

  // Test files get a generous cap; tables of cases legitimately grow.
  if (
    f.endsWith("_test.go") ||
    f.endsWith(".test.ts") || f.endsWith(".test.tsx") ||
    f.endsWith(".spec.ts") || f.endsWith(".spec.tsx") ||
    base.startsWith("test_") || base.endsWith("_test.py")
  ) {
    return { soft: 800, hard: Number.POSITIVE_INFINITY, label: "test" };
  }

  // Go API layout.
  if (f.startsWith("apps/api/internal/http/"))       return { soft: 250, hard: 450, label: "go http" };
  if (f.startsWith("apps/api/internal/handlers/"))   return { soft: 300, hard: 500, label: "go handler" };
  if (f.startsWith("apps/api/internal/database/"))   return { soft: 350, hard: 550, label: "go database" };
  if (f.startsWith("apps/api/internal/services/"))   return { soft: 350, hard: 550, label: "go service" };
  if (f.startsWith("apps/api/internal/middleware/")) return { soft: 200, hard: 400, label: "go middleware" };
  if (f.startsWith("apps/api/internal/storage/"))    return { soft: 250, hard: 450, label: "go storage" };
  if (f.startsWith("apps/api/internal/config/"))     return { soft: 200, hard: 400, label: "go config" };
  if (f.startsWith("apps/api/internal/jobs/"))       return { soft: 250, hard: 450, label: "go jobs" };
  if (f.startsWith("apps/api/internal/ai/"))         return { soft: 250, hard: 450, label: "go ai" };
  if (f.startsWith("apps/api/cmd/"))                 return { soft: 200, hard: 400, label: "go main" };

  // Python worker layout. Service modules are the densest legitimate files.
  if (f.startsWith("apps/worker/fielddesk_worker/providers/")) {
    return { soft: 300, hard: 500, label: "py provider" };
  }
  if (f.startsWith("apps/worker/fielddesk_worker/") && base === "service.py") {
    return { soft: 350, hard: 550, label: "py service" };
  }
  if (f.startsWith("apps/worker/fielddesk_worker/")) {
    return { soft: 300, hard: 500, label: "py worker" };
  }

  // Next.js placeholder app.
  if (f.startsWith("apps/web/app/") && f.endsWith(".tsx"))        return { soft: 300, hard: 500, label: "react page" };
  if (f.startsWith("apps/web/components/") && f.endsWith(".tsx")) return { soft: 300, hard: 500, label: "react component" };
  if (f.startsWith("apps/web/lib/"))                              return { soft: 200, hard: 400, label: "web lib" };

  // Shell scripts: keep small or split.
  if (f.startsWith("scripts/") && (f.endsWith(".sh") || f.endsWith(".cjs") || f.endsWith(".py"))) {
    return { soft: 200, hard: 400, label: "script" };
  }

  return { soft: 300, hard: 500, label: "default" };
}

function hasEscapeHatch(contents) {
  const first = contents.split(/\r?\n/, 1)[0] ?? "";
  return /^(\/\/|#)\s*lint-file-size:/i.test(first);
}

function countLines(contents) {
  return contents
    .split(/\r?\n/)
    .filter((line) => {
      const t = line.trim();
      if (t === "") return false;
      // Skip single-line comments only (not block comments, those are still code-equivalent).
      if (t.startsWith("//") || t.startsWith("#") || t.startsWith("--")) return false;
      return true;
    }).length;
}

const failures = [];
const warnings = [];

for (const filePath of listFiles()) {
  const file = normalize(filePath);
  if (!isCodeFile(file) || isExempt(file) || !existsSync(file)) continue;
  const contents = readFileSync(file, "utf8");
  if (hasEscapeHatch(contents)) continue;

  const lineCount = countLines(contents);
  const rule = ruleFor(file);
  if (lineCount > rule.hard) {
    failures.push({ file, lineCount, limit: rule.hard, label: rule.label });
  } else if (lineCount > rule.soft) {
    warnings.push({ file, lineCount, limit: rule.soft, label: rule.label });
  }
}

for (const w of warnings) {
  console.warn(`⚠️  ${w.file}: ${w.lineCount} lines (${w.label} soft cap ${w.limit})`);
}

if (failures.length > 0) {
  console.error("");
  console.error("❌ file-size: hard caps exceeded");
  for (const f of failures) {
    console.error(`   ${f.file}: ${f.lineCount} lines (${f.label} hard cap ${f.limit})`);
  }
  console.error("");
  console.error("Split the file, or add `// lint-file-size: <reason>` as the first line with a justification.");
  process.exit(1);
}

if (warnings.length === 0 && failures.length === 0) {
  console.log(`✓ file-size: all ${mode === "staged" ? "staged" : "tracked"} files within caps`);
}
