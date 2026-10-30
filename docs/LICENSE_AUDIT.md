# License audit

Exact upstream licenses and pinned commits are in the three reports linked by
UPSTREAM_EVALUATION.md. No upstream code has been copied. Aloha's actual
LICENSE at f998a8b1f132f9b1cd37b86dc20b124be37343a2 is Apache-2.0, resolving the
specification's external-page discrepancy for this commit. Letta branding is
not covered by its Apache code license and is not used.

Build scripts inventory installed distributions, copy their license/notice texts
and generate CycloneDX 1.5 SBOM and platform-specific frozen dependency inventory.
Qt and pynput are dynamically distributed with their license materials. Audit
the actual bundled artifacts before public release. No model weights, upstream
datasets, icons or brand artwork are redistributed. The widget icon is original
Qt drawing code.

The owner has not selected a project source license. LICENSE preserves that
decision instead of assigning an unsolicited open-source license. Development
installers are unsigned; certificate-based release signing is still required.
