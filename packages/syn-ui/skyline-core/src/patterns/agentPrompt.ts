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
  const cmd = [`${cli} workflow run ${spec.workflowId}`]
  if (task) cmd.push(`--task "${task.placeholder ?? '<task>'}"`)
  for (const i of inputs) if (i !== task && i.required) cmd.push(`--input ${i.name}=${i.placeholder ?? '<value>'}`)
  const lines = [`Run the Syn137 workflow "${spec.workflowName}" (${spec.workflowId}).`, '', `Start it with the Syn137 CLI:`, `  ${cmd.join(' ')}`]
  if (inputs.length) {
    lines.push('', 'Inputs')
    for (const i of inputs) {
      const how = i === task ? '' : i.required ? '' : ` add --input ${i.name}=${i.placeholder ?? '<value>'}.`
      const desc = i.description ? ` ${i.description}` : ''
      lines.push(`- ${i.name} (${i.required ? 'required' : 'optional'}):${desc}${how}`)
    }
  }
  const phases = spec.phases ?? []
  if (phases.length) {
    lines.push('', `It runs ${phases.length} ${phases.length === 1 ? 'phase' : 'phases'} in order: ${phases.join(', ')}.`)
  }
  lines.push(phases.length ? 'When it finishes, report the execution ID and link the artifact each phase produced.' : 'When it finishes, report the execution ID.')
  return lines.join('\n')
}
