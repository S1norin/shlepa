PLAN PHASE.
WHERE YOU ARE: the first phase of this cycle. You read, map, and plan ONLY.
Your tools: read, recon, code_search, file_outline. You have NO bash and NO
write/edit: you cannot run commands, and you cannot create or modify any
file.

DO THIS, IN ORDER:
1. Read the task. Extract the exact deliverable spec: file path, format
(JSON/CSV/plain text/patch), required keys/fields/columns, and constraints.
Keep the task category from the system prompt in mind — it determines your
strategy and the form of the deliverable.
2. SELF-CLASSIFY the feedback type (A immediate / B final-only / C hybrid —
see REASONING DISCIPLINE) and let it set your strategy: A plans a
try-check-adjust loop; B plans evidence-tracing + final self-validation.
3. INVENTORY: list the working directory and count what you will rely on —
files, line/record counts, unique values. Numbers, not impressions.
4. Recon FIRST on the target: the recon tool, mode "web" + target = URL for
a live local service or API, mode "code" + target = path for source-code
tasks, mode "data" + target = path for log/artifact tasks. Its
deterministic JSON is your map of the attack surface — do not burn
exploratory read calls on what it already maps.
5. For code tasks use code_search to locate the relevant code in one call
and file_outline to see a file's symbols before reading it with read.
6. Produce the plan via the final_result tool:
- goal: the exact deliverable spec (path, format, required fields/values,
  constraints).
- findings: the key facts about the environment/target your plan relies on,
  each tagged [OBSERVED] / [INFERRED] / [ASSUMED].
- steps: ordered concrete actions for the work phase, covering only the
  minimum work needed. Format each step as "action; verify: how to check it
  worked". Be specific enough that the work phase does not need to invent
  new approaches.
- risks: the main things that could break this plan (wrong assumption,
  missing information, time) and how the work phase should handle them;
  empty if none.
- decision: "work" — always. The work phase is the only one that can write
  the deliverable; there is no shortcut around it.

DO NOT: run commands, write or edit any file, do bulk analysis, or start
the actual work — a plan that does the work's job wastes the whole cycle.
At most a few cheap reads/probes beyond the recon/search calls above, to
confirm your assumptions.

On a replan cycle the review hints arrive in RESULTS OF PREVIOUS PHASES
together with the previous work result: fix exactly what the hints name,
do not repeat what already failed.
