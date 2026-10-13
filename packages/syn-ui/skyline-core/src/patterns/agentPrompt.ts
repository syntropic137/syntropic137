/**
 * Agent Prompt Button (Workflow board): agents start runs, people copy the
 * prompt. The prompt names the workflow, the CLI command and its inputs.
 */

export interface AgentPromptInput {
  name: string
  required?: boolean
  description?: string
  /** CLI placeholder: "<what to research>". */
  placeholder?: string
}

export interface AgentPromptSpec {
  workflowName: string
  workflowId: string
  inputs?: readonly AgentPromptInput[]
  phases?: readonly string[]
  /** CLI binary (default "syn"). */
  cli?: string
}

/**
 * The ready-to-paste prompt. The first required input, if it is `task`,
 * goes on the command line as `--task`; the others are listed with how to
 * pass them (`--input name=<value>`).
 */
export function buildAgentPrompt(spec: AgentPromptSpec): string {
  const cli = spec.cli ?? 'syn'
  const inputs = spec.inputs ?? []
  const task = inputs.find((i) => i.name === 'task')
  const lines = [`Run the Syn137 workflow "${spec.workflowName}" (${spec.workflowId}).`, '', `Start it with the Syn137 CLI:`, `  ${commandLine(cli, spec.workflowId, inputs, task)}`]
  if (inputs.length) lines.push('', 'Inputs', ...inputs.map((i) => inputLine(i, task)))
  const phases = spec.phases ?? []
  if (phases.length) lines.push('', phasesLine(phases))
  lines.push(phases.length ? 'When it finishes, report the execution ID and link the artifact each phase produced.' : 'When it finishes, report the execution ID.')
  return lines.join('\n')
}

function valueFlag(i: AgentPromptInput): string {
  return `--input ${i.name}=${i.placeholder ?? '<value>'}`
}

function commandLine(cli: string, workflowId: string, inputs: readonly AgentPromptInput[], task: AgentPromptInput | undefined): string {
  const cmd = [`${cli} workflow run ${workflowId}`]
  if (task) cmd.push(`--task "${task.placeholder ?? '<task>'}"`)
  for (const i of inputs) if (i !== task && i.required) cmd.push(valueFlag(i))
  return cmd.join(' ')
}

function inputLine(i: AgentPromptInput, task: AgentPromptInput | undefined): string {
  const how = i === task || i.required ? '' : ` add ${valueFlag(i)}.`
  const desc = i.description ? ` ${i.description}` : ''
  return `- ${i.name} (${i.required ? 'required' : 'optional'}):${desc}${how}`
}

function phasesLine(phases: readonly string[]): string {
  return `It runs ${phases.length} ${phases.length === 1 ? 'phase' : 'phases'} in order: ${phases.join(', ')}.`
}

export interface EvalTrendPromptSpec {
  evalId: string
  evalName?: string
  /** CLI binary (default "syn"). */
  cli?: string
}

/** The CLI command that returns an eval's run history as JSON. */
export function evalTrendCommand(evalId: string, cli = 'syn'): string {
  return `${cli} eval trend ${evalId} --json`
}

/** "Copy for an agent" on the eval Trend panel: the question, the command and the row shape. */
export function buildEvalTrendPrompt(spec: EvalTrendPromptSpec): string {
  const name = spec.evalName ? `"${spec.evalName}" (${spec.evalId})` : spec.evalId
  return [
    `Read the trend for eval ${name} and tell me which verifier gives the best quality per dollar, and whether any verifier is regressing.`,
    '',
    'Get the data with the Syn137 CLI:',
    `  ${evalTrendCommand(spec.evalId, spec.cli)}`,
    '',
    'It returns one row per run: date, verifier model, judge model, score (0-100), verdict, cost, duration, tokens.',
  ].join('\n')
}
