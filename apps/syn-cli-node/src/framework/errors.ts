export class CLIError extends Error {
  readonly exitCode: number;

  constructor(message: string, exitCode = 1) {
    super(message);
    this.name = "CLIError";
    this.exitCode = exitCode;
  }
}
