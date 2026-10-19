---
name: diagnostic-experiment-matrix
description: "Build a diagnostic experiment matrix to find root causes when theories keep failing. Use when a bug has resisted multiple fix attempts, when the same issue keeps recurring with different symptoms, when unit tests pass but production fails, when the real execution path has layers (pipelines, remote execution, multi-hop command chains) that mocks don't cover, or when the team is stuck theorizing about root cause. Triggers: 'we tried X and it didn't work', 'the fix works in tests but not in production', 'we don't know why this is happening', 'multiple attempts failed', 'theory doesn't match behavior', 'works locally but fails remotely', 'can't reproduce in tests'."
---

# Diagnostic Experiment Matrix

When a bug resists multiple fix attempts, stop theorizing and start experimenting.
Build a test that exercises ALL plausible paths simultaneously through the REAL execution environment, then read back empirical results.

## When to Use This

- Multiple fix iterations failed (each based on a different theory)
- Unit tests pass but production fails (mocked layers hide the real bug)
- The execution path has multiple hops/layers (SSH, WinRM, containers, shells, adb)
- Everyone has a theory but nobody has proof
- The symptom is clear but the mechanism is unknown

## The Anti-Pattern This Replaces

```
Theory A → Fix A → Still broken
Theory B → Fix B → Still broken  
Theory C → Fix C → Still broken (3 weeks wasted)
```

## The Pattern

```
1. List ALL plausible hypotheses (even ones that seem unlikely)
2. Build ONE test that exercises every hypothesis as a separate experiment
3. Each experiment: identical setup → single variable changed → observe outcome
4. Run once → read results → root cause is usually obvious
5. Fix the actual problem (often something nobody theorized about)
```

## How to Build the Experiment Matrix

### Step 1: Define the Observable

What is the DIRECT evidence of correct/incorrect behavior?
Not "the test passes" but "PID 12345 exists after the kill command."
Not "throughput is good" but "process X is alive AND process Y is dead."

Go as close to the source of truth as possible.
If the bug is about processes dying: check PIDs directly.
If the bug is about data: check the file content directly.
If the bug is about commands: capture what was actually sent.

### Step 2: List All Variables

What could possibly differ between "works" and "doesn't work"?

Examples from real debugging:
- Signal type (SIGINT vs SIGTERM vs SIGKILL)
- Pattern format (quoted vs unquoted, spaces vs dots)
- Execution context (run-as vs plain shell)
- Which PID is targeted (first only vs all)
- With/without a wrapper (setsid vs direct)

### Step 3: Design Experiments

Each experiment changes exactly ONE variable.
Every experiment uses the same setup (start fresh, observe before, act, observe after).

Template:
```
SETUP (identical for all)
├── Clean state (kill leftovers)
├── Start the system under test
└── Wait for steady state

EXPERIMENT N: [description of single variable]
├── OBSERVE BEFORE (capture full state)
├── ACT (the one thing that differs)
├── WAIT (for effects to propagate)
└── OBSERVE AFTER (capture full state again)

CLEANUP (reset for next experiment)
```

### Step 4: Make It Non-Fatal

Every observation step should LOG results but NEVER FAIL the test.
Use info-level logging, soft assertions or try-catch wrappers.
The goal is to collect data from ALL experiments, not abort on first issue.

### Step 5: Include Infrastructure Diagnostics

Before any experiment, capture:
- System version/environment info
- Current state (any leftover processes/connections)
- Tool availability (is `setsid` present? is `pkill` available?)

These often reveal the answer before experiments even run.

## Common Revelations

| What everyone theorized | What the experiment revealed |
|---|---|
| "Signal propagation between processes" | Pattern matching returned wrong PIDs |
| "Race condition in timing" | Command never executed (quoting issue) |
| "Permission/security model" | Wrong target (path resolution) |
| "Network timeout" | Connection string malformed by pipeline |
| "OS-level behavior" | Intermediary (shell, PowerShell, proxy) transformed the command |

**The most common hidden root cause: multi-layer command pipelines mangle arguments.**

When a command passes through 3+ layers (Java → WinRM → PowerShell → cmd → SSH → shell), each layer interprets quotes, spaces, and special characters differently.
Symptoms look like "the OS is doing something weird" but actually the command that arrives is different from what was sent.

## Debugging Multi-Layer Pipelines Specifically

If the execution path is: `App → Layer1 → Layer2 → ... → Target`

1. Add an experiment that echoes the command at the target (instead of executing it)
2. Compare what was SENT vs what ARRIVED
3. Common mangling: `$()` interpreted by intermediate shell, quotes stripped, spaces split arguments

Quick fixes:
- Replace spaces with regex dots (`.`) in patterns
- Avoid subshell syntax (`$()`, backticks) in commands that traverse shells
- Use single-token commands where possible (no embedded spaces in arguments)
- Prefer tools that combine find+act atomically (`pkill` vs `pgrep` + `kill`)

## After the Experiment

Once you know the root cause:
1. Fix the actual problem (usually simpler than any of the theoretical fixes)
2. Add a regression check that verifies the FIX MECHANISM, not just the symptom
3. If possible, verify the fix catches all previous broken iterations

A good regression test after experiment-driven diagnosis has multiple layers:
- **Direct state check** (is the correct thing alive/dead/present?)
- **Negative check** (is the wrong thing NOT happening?)
- **Data validity check** (did the system produce correct output?)
