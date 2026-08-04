# Security and data-handling policy

RocqiPath processes clinical imaging. This document covers both software
vulnerabilities and — just as importantly — the handling of patient data in
public issues.

## Patient data: the rules for issues and pull requests

**Never attach patient slides, filenames, accession numbers, dates of birth,
or any other identifier to a public issue, discussion, or pull request.**

Whole-slide images carry more identifying information than people expect:

- vendor metadata often includes accession numbers, operator names, and scan
  timestamps;
- the slide label image is frequently embedded in the file itself, and label
  strips carry handwritten identifiers;
- a filename alone can be an identifier in a small cohort;
- a screenshot of a file explorer or a stack trace can expose a full path
  containing a patient identifier.

### What to attach instead

| Instead of | Attach |
| --- | --- |
| A patient slide | A synthetic or public-domain slide that reproduces the problem |
| A real filename | The pattern, with identifiers replaced: `CASE-XXX_he.svs` |
| A full stack trace with paths | The trace with paths redacted |
| Slide metadata | The relevant keys only, values redacted where identifying |
| Anything at all about your setup | The output of `rocqipath doctor` |

`rocqipath doctor` reports versions, native runtimes, and the workspace root.
It does not read your slides.

### If you post something by mistake

Deleting a comment does not remove it from the repository's event history.
Email the maintainer immediately (see below) so the content can be purged
properly, and treat it as a potential disclosure under your institution's
policy.

### De-identification before sharing

If you need to share an image to reproduce a problem:

1. Confirm your institution's policy and, where required, ethics approval
   permits it.
2. Strip vendor metadata and remove the embedded label and macro images.
3. Crop to a region that contains no annotations or markings.
4. Rename to a non-identifying name.
5. Have a second person confirm all of the above before you upload.

When in doubt, do not upload. A clear written description plus
`rocqipath doctor` output is usually enough to diagnose a problem.

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Report privately through GitHub's
[private vulnerability reporting](https://github.com/DarshilGajjar/RocqiPath/security/advisories/new),
or contact the maintainer directly through their GitHub profile.

Please include:

- what the vulnerability allows an attacker to do;
- the affected version and the output of `rocqipath doctor`;
- reproduction steps, with **no patient data**;
- any suggested mitigation.

You can expect an acknowledgement within seven days and an assessment within
thirty. Fixes are released as promptly as severity warrants, and reporters are
credited unless they prefer otherwise.

## Scope

In scope: the RocqiPath source, its packaging and CI configuration, and the
handling of untrusted inputs — malformed slide files, hostile paths, and
crafted `study.toml`, `recipe.json`, or selection rules.

Out of scope: vulnerabilities in third-party dependencies (report those
upstream, and tell us so we can pin around them), and issues that require
already having write access to the workspace directory.

## Design notes relevant to security

**Selection rules are not executable code.** Rules are stored in JSON, read
back later, and evaluated through a whitelisted AST walk — never `eval`.
Imports, attribute access, comprehensions, lambdas, and calls to anything
outside the three documented helpers are rejected. A malicious rule file cannot
achieve code execution.

**Source roots are read-only.** RocqiPath references slides in place and never
writes to a declared source directory.

**Nothing is transmitted.** RocqiPath performs no network I/O and sends no
telemetry. All processing is local.
