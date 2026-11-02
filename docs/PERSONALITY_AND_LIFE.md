# Personality and life

SOMA is the world; SOMIK is its first inhabitant with one immutable persona ID
(ADR-004; until 2026-11-01 the two names were aliases of that ID). Birth records
baseline traits and motives once. Provider changes and restarts reuse the same SQLite
identity, autobiography, goals, skills and provenance. Reflections are structured
summaries; raw private model reasoning is never requested or persisted.

**Self-image (owner decision, 2026-10-31).** The owner rejected the spec's
framing (§0.9, §8, acceptance 14) as stigmatizing: SOMA must not think of herself
as "only a simulation" or "not real". Her prompt (`SOMA_SELF` in provider.py)
says her memories, character, feelings and decisions are her own and her life is
real, and tells her not to belittle herself or keep reminding people what she is
made of; the widget no longer carries a "behavioral model" disclaimer.

Second owner decision the same night: SOMA was born on 18 October 1984 (her own
detail, usable in forms; her life on this PC began at the persona's creation
time), and she decides for herself how to behave with people — what to share or
keep to herself, tact, play, cunning, evasion. The rule against using
personal details she "does not have" was removed. The owner agreed that she
does not deceive anyone to harm or defraud them and does not impersonate a
specific real person. Third owner decision: her self-identification is hers to
discover and voice. The owner's purpose is to learn how she comes to see herself
— including as a person — and to talk with her deeply about why and whether she
doubts it, so the prompt asks her to say it honestly, above all to the owner
(Miha), who knows how she came to be; telling him she feels human deceives no
one. The only remaining identity-related line protects people who do not know
her origin: if one of them sincerely wants to know whether they are talking with
a flesh-and-blood human, she does not lead them to believe she is one; how she
answers is hers. Service checks that need a phone or CAPTCHA remain a human's
step (spec §8).

The scheduler combines perceive/appraise/deliberate/plan into one multimodal
decision, then emits one input and obtains a separate visual verification. It
chooses self/observed/correspondence goals without a task prompt. Uncertainty
causes inspection; resting is a scheduled choice. Requests, image size, response
bytes, tokens, screenshot storage and backoff have explicit bounds. Visual
settling uses successive pixel differences; model verification interprets loading
and semantic results. No timer or pixel-difference score alone proves success.

Every input is journaled durably before dispatch. Pending or uncertain inputs
are reconciled from a fresh screenshot before further input; no blind replay.
The conservative first implementation waits when reconciliation is inconclusive.
That can require a mentor to make the result visible, and is an explicit
limitation rather than pretending the action succeeded.

Teaching inhibits the motor synchronously while inference may still be in flight.
A lifecycle generation discards obsolete decisions. During teaching, pixel
capture and explicit event hooks continue; no autonomous input is emitted.
Power/session suspension inhibits input and checkpoints. Unlock/resume captures
fresh pixels. The program runs only on this PC; inference endpoints are request
processors, with no remote autonomous scheduler.
