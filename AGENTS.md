# Session handoff

Before ending, resetting, or compacting a work session:

1. Finish or interrupt the active operation at a coherent boundary.
2. Emit one progress update using only the applicable fields:

   ```text
   Objective: <objective>
   Completed:
   - <completed item>
   Current operation: <current operation>
   Next operation: <next operation>
   Completion criteria:
   - <completion criterion>
   Open questions:
   - <open question>
   ```

3. Run:

   ```bash
   uv run handoff create
   ```

4. The command stages repository changes and derives `handoff.json` from the
   staged Git state and current Codex rollout.
5. Do not manually author or modify the generated handoff.
6. Continue from the emitted JSON path in the next session.
