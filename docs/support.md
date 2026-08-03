# Forge Support

Forge is maintained by Alisina Karimi in the public
[AlisinaDevelo/md-files repository](https://github.com/AlisinaDevelo/md-files).

## Before opening an issue

1. Check the [getting started guide](getting-started.md) and
   [release provenance guide](release-provenance.md).
2. Run `./scripts/validate.sh` and record the Forge version, host, operating system, and
   smallest reproducible command.
3. For installation problems, include the relevant `claude plugin list` or
   `codex plugin list` result, but redact tokens, private repository names, and personal
   paths where possible.

## Support channels

- **Bug or feature:** use the repository's
  [issue tracker](https://github.com/AlisinaDevelo/md-files/issues) and select the
  appropriate template.
- **Security vulnerability:** use the private
  [security advisory flow](https://github.com/AlisinaDevelo/md-files/security/advisories/new)
  described in [SECURITY.md](../SECURITY.md). Do not publish exploit details in an issue.
- **Release or installation question:** open an issue with the release tag, host, and
  verification output. The maintainer owns release/update decisions for this project.

## Compatibility expectations

The latest `main` and latest tagged release receive primary support. Older releases may
continue to work but are not guaranteed to receive fixes. Every release records its
source commit, archive hashes, SBOM, and verification instructions; use those artifacts
when reporting a suspected distribution problem.
