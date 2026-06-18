## What

<!-- One-paragraph summary of the change. -->

## Why

<!-- The motivation. Link any related issue. -->

## How

<!-- The approach and any non-obvious decisions or trade-offs. -->

## Type of change

- [ ] New agent
- [ ] New skill
- [ ] New command
- [ ] New / changed hook
- [ ] Instructions / docs
- [ ] Tooling / CI
- [ ] Fix or improvement to an existing artifact

## Checklist

- [ ] `./scripts/validate.sh` passes
- [ ] Markdown is lint-clean
- [ ] Descriptions trigger reliably without over-firing (agents/skills)
- [ ] Tools are scoped to least privilege (agents/commands)
- [ ] Hooks fail open on bad input and only hard-block high-confidence issues
- [ ] Commits follow Conventional Commits, with no AI co-author trailer
- [ ] CHANGELOG updated if user-facing
