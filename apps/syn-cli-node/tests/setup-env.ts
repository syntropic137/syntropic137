// WHY: the CLI reads these from the environment, some of them at import time
// (the typed client builds its base URL from SYN_API_URL when first imported).
// Whatever the developer's shell exports would otherwise leak into every test
// file before its own vi.stubEnv runs, so a test passes in CI and fails on a
// machine pointed at a real deployment. Each file starts from a machine with
// none of them set; a test that needs one stubs it.
const AMBIENT_ENV = [
  "SYN_API_URL",
  "SYN_API_TOKEN",
  "SYN_API_USER",
  "SYN_API_PASSWORD",
  "NO_COLOR",
] as const;

for (const name of AMBIENT_ENV) delete process.env[name];
