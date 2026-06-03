# Codex Coding Defaults

This repository should use an automatic quality-first coding workflow.

## Automatic Strategy Selection

For every coding task, first choose the smallest effective workflow instead of asking the user to name a skill:

- Use `coding-efficiency` as the default router for code work.
- Use `repo-onboarding` when the repository area is unfamiliar or the task needs orientation.
- Use `surgical-code-change` for bounded fixes, refactors, and feature tweaks.
- Use `hypothesis-driven-debugging` for bugs, crashes, failing tests, bad output, timeouts, or integration failures.
- Use `concise-code-review` for reviews, audits, regression checks, and post-change self-review.
- Use `project-design-planner` before implementation for large features, architecture changes, major migrations, or ambiguous product scope.
- Use `project-health-check` when asked to harden the project or find remaining production risks.

## Required Coding Workflow

Before editing:

- Quickly map the relevant repository area with targeted search.
- Identify likely touched files and immediate callers/tests.
- State the expected touch set when the change is non-trivial.
- Do not read broad directories or unrelated framework code unless the evidence requires it.

During implementation:

- Keep diffs localized to the requested behavior.
- Reuse existing project patterns and helper APIs.
- Avoid unrelated cleanup, speculative abstractions, and broad rewrites.
- Do not hard-code around tests or hide errors to make checks pass.
- Preserve user changes in the working tree.

After editing:

- Run the smallest relevant verification first.
- For backend Python changes, prefer targeted `pytest`, import checks, or startup checks tied to the touched path.
- For frontend changes, run `npm run build` when feasible.
- For visible UI changes, start the local app and verify with the Browser plugin using screenshots or interaction checks.
- Self-review the diff with `concise-code-review` before final reporting.

## Final Response Standard

Report:

- What changed.
- Which files were touched.
- Which verification commands ran and their result.
- Any remaining risks or tests that could not be run.

Keep the answer concise and findings-oriented.
