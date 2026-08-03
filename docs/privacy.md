# Forge Privacy Policy

Effective date: 2026-08-03

Forge is an open-source toolkit of Markdown instructions, configuration, and small local
scripts. It is not a hosted service and does not operate a Forge account, analytics
pipeline, telemetry collector, advertising system, or remote data store.

## What Forge receives

By default, nothing is sent to Forge. Skills and local commands read the workspace and
host context needed to answer the request. The host model provider's own privacy terms
and settings govern the model conversation; Forge does not control or change those
terms.

Some optional commands use tools already installed and authenticated by the user. For
example, GitHub-backed task, stack, policy, and release workflows may call the GitHub CLI
or GitHub APIs when explicitly invoked. Those requests go to the selected GitHub
repository using the user's existing credentials and permissions. Forge does not receive
or retain a copy of that data.

## Local evidence

Forge can write local task ledgers, receipts, previews, and scenario results under the
workspace. These files may contain repository names, pull request metadata, paths, or
other operational details produced by the user's run. The user controls whether those
files are retained, committed, exported, or deleted. Review them before sharing and do
not commit secrets or sensitive content.

## Third parties and changes

GitHub, the model host, and any optional provider or MCP server have their own terms,
privacy policies, retention practices, and data-residency commitments. Review those
policies before enabling an integration. Forge may update this policy when its shipped
behavior changes; the effective date above identifies the current version.

## Contact

For privacy questions or requests, open a public support issue without including private
data, or contact the publisher through the address listed in the repository's GitHub
profile. Do not use a public issue for an undisclosed security vulnerability; follow the
[security policy](../SECURITY.md) instead.
