/**
 * Configuration commands — show, validate, env.
 * Local-only: reads CLI configuration from environment, does not call the API.
 */

import { CommandGroup, type CommandDef } from "../framework/command.js";
import { CLIError } from "../framework/errors.js";
import { getApiUrl, getAuthHeaders, CLI_VERSION } from "../config.js";
import { print } from "../output/console.js";
import { style, BOLD, GREEN, RED, DIM } from "../output/ansi.js";

const showCommand: CommandDef = {
  name: "show",
  description: "Display current CLI configuration",
  handler: async () => {
    const apiUrl = getApiUrl();
    const headers = getAuthHeaders();
    const hasAuth = Object.keys(headers).length > 0;
    const authType = headers["Authorization"]?.startsWith("Bearer")
      ? "token"
      : headers["Authorization"]?.startsWith("Basic")
        ? "basic"
        : "none";

    print(style("CLI Configuration", BOLD));
    print(`  Version:  ${CLI_VERSION}`);
    print(`  API URL:  ${apiUrl}`);
    print(`  Auth:     ${hasAuth ? style(authType, GREEN) : style("none", DIM)}`);
    print("");
    print(style("Environment Variables", BOLD));
    print(`  SYN_API_URL:      ${process.env["SYN_API_URL"] ?? style("(default: http://localhost:8137)", DIM)}`);
    print(`  SYN_API_TOKEN:    ${process.env["SYN_API_TOKEN"] ? style("set", GREEN) : style("not set", DIM)}`);
    print(`  SYN_API_USER:     ${process.env["SYN_API_USER"] ?? style("not set", DIM)}`);
    print(`  SYN_API_PASSWORD: ${process.env["SYN_API_PASSWORD"] ? style("set", GREEN) : style("not set", DIM)}`);
  },
};

const validateCommand: CommandDef = {
  name: "validate",
  description: "Validate CLI configuration",
  handler: async () => {
    const issues: string[] = [];
    const apiUrl = getApiUrl();

    if (!apiUrl.startsWith("http://") && !apiUrl.startsWith("https://")) {
      issues.push("SYN_API_URL must start with http:// or https://");
    }

    const headers = getAuthHeaders();
    let isLocal = false;
    try {
      const parsed = new URL(apiUrl);
      isLocal = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
    } catch { /* invalid URL already caught above */ }

    if (Object.keys(headers).length === 0 && !isLocal) {
      issues.push("No authentication configured for non-localhost API URL");
    }

    if (issues.length === 0) {
      print(style("Configuration is valid.", GREEN));
    } else {
      for (const issue of issues) {
        print(`${style("!", RED)} ${issue}`);
      }
      throw new CLIError("Configuration has issues", 1);
    }
  },
};

const envCommand: CommandDef = {
  name: "env",
  description: "Show environment variable template",
  handler: async () => {
    print("# Syntropic137 CLI configuration");
    print("# Copy and adjust these variables in your shell profile");
    print("");
    print("# API server URL (default: http://localhost:8137)");
    print("export SYN_API_URL=http://localhost:8137");
    print("");
    print("# Authentication (choose one):");
    print("# Option 1: Bearer token");
    print("export SYN_API_TOKEN=your-token-here");
    print("");
    print("# Option 2: Basic auth");
    print("# export SYN_API_USER=admin");
    print("# export SYN_API_PASSWORD=your-password-here");
  },
};

export const configGroup = new CommandGroup("config", "CLI configuration");
configGroup.command(showCommand).command(validateCommand).command(envCommand);
