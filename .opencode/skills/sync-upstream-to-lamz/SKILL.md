---
name: sync-upstream-to-lamz
description: Use when syncing upstream changes into this nanobot fork and merging them into lamz without damaging lamz-specific behavior.
---

# Nanobot Repo Workflow

This skill is only for the upstream sync workflow of this fork.

## Branch Policy

- Only three branches matter by default: `upstream`, `main`, and `lamz`.
- `upstream` is the read-only remote `HKUDS/nanobot` source.
- `main` is a sync branch only.
- `lamz` is the real development branch of this fork.
- Always flow changes as `upstream/main -> main -> lamz`.
- Do not merge upstream directly into `lamz` unless the user explicitly asks.

## Required Sync Sequence

When the user asks to pull upstream changes into the fork, use this exact order:

```bash
git fetch upstream
git checkout main
git merge upstream/main --ff-only
git push origin main
git checkout lamz
git merge main --no-ff
pytest tests/
git push origin lamz
```

## Safety Rules

- Check `git status` before branch operations.
- Do not discard or overwrite user changes.
- Do not rewrite `lamz` history unless the user explicitly asks.
- Preserve `lamz`-specific commits and behavior during merge conflict resolution.
- If `main` already contains the latest `upstream/main`, do not invent extra sync steps.
- If stray feature branches exist, do not use them for this workflow.

## Merge Intent

The purpose of `main` is to mirror upstream safely.

The purpose of merging `main` into `lamz` is to bring upstream updates into the fork while keeping fork-specific behavior intact.

When conflicts happen, resolve them conservatively:

- keep upstream improvements where they do not break fork behavior
- keep `lamz` behavior where the fork has intentional divergence
- prefer the smallest safe merge that preserves both goals

## Completion Checklist

Before reporting success, confirm all of the following:

- `main` matches `upstream/main`
- `lamz` contains the merged `main` changes
- `lamz`-specific behavior was preserved
- relevant verification was run after the merge
- only the expected branches were used in the workflow
