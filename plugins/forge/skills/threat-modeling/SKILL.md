---
name: threat-modeling
description: >-
  Use when designing or reviewing a feature for security before it ships — to
  systematically identify what can go wrong and where the defenses must be. Covers
  the STRIDE method, trust boundaries, and turning threats into concrete controls.
  Defensive use only.
---

# Threat Modeling

Answer four questions: **What are we building? What can go wrong? What do we do about
it? Did we do a good job?** Do it early — design-time fixes are far cheaper than
post-incident ones.

## 1. Model the system

Sketch the data flow: external entities, processes, data stores, and the flows between
them. Mark **trust boundaries** — every point where data crosses from less-trusted to
more-trusted (internet → server, user → admin, service → database). Threats cluster at
boundaries.

## 2. Enumerate threats — STRIDE

For each element and flow, ask which apply:

| Threat | Property violated | Example |
|--------|-------------------|---------|
| **S**poofing | Authentication | forging a user's identity, stolen token |
| **T**ampering | Integrity | modifying data in transit or at rest |
| **R**epudiation | Non-repudiation | denying an action; no audit trail |
| **I**nformation disclosure | Confidentiality | leaking PII, secrets in logs |
| **D**enial of service | Availability | resource exhaustion, unbounded work |
| **E**levation of privilege | Authorization | user gains admin, IDOR, missing authz |

Walk untrusted input from each entry point to every sink it can reach.

## 3. Decide on controls

For each credible threat, choose: **mitigate** (add a control), **eliminate** (remove the
feature/data), **transfer** (offload to a vetted provider), or **accept** (document the
residual risk and why). Map threats to concrete defenses:

- Spoofing → strong authN, MFA, signed/short-lived tokens.
- Tampering → TLS, integrity checks, server-side validation, least privilege.
- Repudiation → audit logging of security-relevant actions.
- Disclosure → encryption in transit/at rest, minimize data, scrub logs.
- DoS → rate limits, timeouts, quotas, bounded input sizes.
- EoP → authorize every action, default-deny, separation of duties.

## 4. Validate

Did each high-severity threat get a control? Are controls testable? Add tests/alerts for
the important ones. Re-model when the design changes materially.

## Prioritize

Risk = likelihood × impact. Fix the exposed, high-impact, easy-to-exploit issues first.
Don't drown the design in low-severity theoreticals — focus on what an attacker would
actually reach and abuse.
