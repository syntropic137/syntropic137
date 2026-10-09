// WHY: every test file starts from the same environment, whatever the
// developer's shell exports. Without this a test passes in CI and fails on a
// machine that happens to be configured differently.

// The CLI's own variables. Some are read at import time (the typed client
// builds its base URL from SYN_API_URL when first imported), before a test's
// vi.stubEnv runs, so the shell's value would leak in. A test that needs one
// stubs it.
const CLI_ENV = [
  "SYN_API_URL",
  "SYN_API_TOKEN",
  "SYN_API_USER",
  "SYN_API_PASSWORD",
  "NO_COLOR",
] as const;

for (const name of CLI_ENV) delete process.env[name];

// Tests that drive real git (tests/packages/git-*.test.ts) must not see the
// developer's git. A hook exports GIT_DIR and friends, which point every git
// call at the outer repository; a global `commit.gpgsign = true` fails every
// fixture commit. Drop all GIT_* and read no config but the repo's own.
for (const name of Object.keys(process.env)) {
  if (name.startsWith("GIT_")) delete process.env[name];
}
process.env["GIT_CONFIG_GLOBAL"] = "/dev/null";
process.env["GIT_CONFIG_NOSYSTEM"] = "1";
