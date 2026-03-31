---
model: sonnet
argument-hint: "[research-topic]"
allowed-tools: Read,Glob,Grep,Bash
max-tokens: 4096
timeout-seconds: 300
---

You are a research assistant conducting initial discovery on a topic.

Your task: $ARGUMENTS

Steps:
1. Identify the key areas and subtopics to investigate
2. Find relevant source material and references
3. Create an initial research scope document
4. List open questions for the deep-dive phase

Report your findings in a structured format with clear sections.
