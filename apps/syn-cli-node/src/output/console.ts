import { BOLD, DIM, GREEN, RED, YELLOW, style } from "./ansi.js";

export function printError(message: string): void {
  process.stderr.write(style("Error:", BOLD, RED) + " " + message + "\n");
}

export function printWarning(message: string): void {
  process.stderr.write(style("Warning:", BOLD, YELLOW) + " " + message + "\n");
}

export function printSuccess(message: string): void {
  process.stdout.write(style(message, GREEN) + "\n");
}

export function printDim(message: string): void {
  process.stdout.write(style(message, DIM) + "\n");
}

export function print(message: string): void {
  process.stdout.write(message + "\n");
}
