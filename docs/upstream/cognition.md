# Cognition, provider and benchmark upstream audit

Audit date: 2026-10-30. All four repositories were cloned with `--depth 1 --filter=blob:none` under `.upstream/`; OSWorld was then fetched and detached at the recommended tag. This is source inspection plus small offline probes on Windows x64, not a claim of model inference or a desktop benchmark pass. No upstream implementation or assets were copied into SOMA production code.

| Candidate | Audited commit | Decision |
| --- | --- | --- |
| QwenLM/Qwen3-VL | `96588727e44c78b25ba03ea03b8e12f7e64fd0da` | Adapt the inference contract; reference grounding/resize patterns; do not import its general tool executor |
| letta-ai/letta-code | `ebc496e532f1a34da9ac8d7e2da41c5920ea77e6` (package 0.34.33) | Reference identity/context continuity and bounded reflection; own local persistence |
| joonspk-research/generative_agents | `fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4` | Reference episodic retrieval, evidence-linked reflection and planning concepts |
| xlang-ai/OSWorld-V2 | `3d778a3c9a34a079316f70df023b166700445792` (`osworld-v2.1`) | Benchmark only; excluded from runtime |

## Qwen3-VL

Read the repository README, LICENSE, the computer-use notebook, `cookbooks/utils/agent_function_call.py`, and `qwen-vl-utils/src/qwen_vl_utils/vision_process.py`. The repository LICENSE is Apache-2.0. Any future redistributed code needs the license, retained notices and modification notices as applicable; do not treat the code license as blanket clearance for arbitrary weights or third-party assets.

The official weight cards independently identify [Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct/blob/89644892e4d85e24eaac8bacfd4f463576704203/README.md) and its [FP8 variant](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-FP8/blob/46485250d8854c0a9be4f1adbc67ca47e5bb6fa5/README.md) as Apache-2.0. Their repository HEADs were resolved with `git ls-remote`; no weight files were downloaded or bundled. FP8 is an official quantized candidate, but its card directs deployment through vLLM/SGLang and says direct Transformers loading is unsupported. This is no evidence of useful performance on integrated graphics. Other quantizers, GGUF conversions and their exact artifacts remain separately unverified.

Provider adaptation: accept immutable screenshot bytes and internal context, return a strictly validated action description. Own the coordinate transform between resized/normalized model coordinates and physical monitor coordinates. The upstream computer-use example describes successive screenshot observation. `smart_resize` preserves a token/pixel budget and factor alignment; preserve geometry metadata so it cannot silently move click targets. `fetch_image` accepts arbitrary local paths, HTTP URLs and file URLs: these routes must not be exposed to a model. SOMA supplies only its own captured image bytes. Exclude mobile ADB actions, application-opening shortcuts, external tools and arbitrary executor code.

Platform evidence: README documents Transformers and Linux-oriented vLLM/Docker deployments, explicitly notes that non-Linux `decord` wheels may be unavailable and gives a torchvision fallback. The large FP8 serving example requires NVIDIA H100+/CUDA 12+. There is no native Windows/iGPU throughput evidence in this audit. Remote inference is the baseline; local small-model operation remains an explicit experimental profile.

## Letta Code

Read README and LICENSE plus `src/backend/local/local-agent-record.ts`, `local-agent-record-file.ts`, `local-transcript.ts`, `src/reflection-settings.ts`, `src/agent/reflection-runs.ts`, `src/cli/helpers/reflection-memory-v2.ts`, `src/memory-constraints.ts`, and `src/providers/byok-providers.ts`.

The code LICENSE is Apache-2.0 **with a Brand Assets Exclusion**: Letta names, logos, images and ASCII art require separate written permission. None are included in SOMA. Letta supplies a harness, not model weights; every chosen model/provider retains separate terms.

Useful patterns: stable agent ID separate from model configuration; schema-versioned transcript manifests; bounded context projection instead of sending every memory; reflection scoped to the active agent/conversation; explicit memory budgets; unreadable records quarantined rather than silently re-created as another identity. SOMA should use transactional local storage rather than inherit Git/cloud as an always-on dependency. Identity and event history remain authoritative across provider replacement. New summaries/skills cite source events and are new versions, not edits to the autobiography.

Excluded: Telegram/Slack/Discord integrations, direct computer/file tools, hooks, shell and MCP tooling, remote computer routing, provider credential readers outside SOMA's own settings, self-modifying harness execution. Internal model inference calls are allowed; application service APIs are not.

Platform evidence: README lists Windows x64 and glibc Linux 2.28+ x86-64/ARM64 wheels, with unsupported Windows ARM64/32-bit/Alpine. `isAutoReflectionEnabled()` disables automatic client-side reflection on native Windows unless `LETTA_ENABLE_WINDOWS_AUTO_REFLECTION=1`; manual reflection is unaffected. SOMA therefore owns a platform-neutral, session-bound reflection scheduler and must not inherit this limitation or run thought processes after its PC sleeps.

## Generative Agents

Read README, LICENSE, `persona.py`, `memory_structures/associative_memory.py`, `cognitive_modules/perceive.py`, `retrieve.py`, and `reflect.py`. Code LICENSE: Apache-2.0. README additionally requests citation for code/data use and credits separately authored game art. No town simulation, data, sprites or prompts are included in SOMA. Its model calls depend on external OpenAI inference rather than bundled weights.

Useful patterns: event/thought/chat memory nodes contain creation/expiration, importance, keywords, embeddings and evidence (`filling`); retrieval combines relevance, recency and importance; reflections are derived nodes linked to observed evidence; persistent persona state is loaded for continuation. Adapt these as concepts with screen/action/demo provenance, confidence and explicit observation/inference distinction. Upstream JSON files are written separately and are not an atomic crash-safe multi-record store; SOMA needs SQLite transactions and an append-only event log.

Excluded: reading maze tiles, game-world object state, persona dictionaries and environment files as external perception. Their simulation world is not a compliant SOMA desktop interface. Their direct inter-persona conversations do not replace GUI messaging.

Platform evidence: README reports testing Python 3.9.12 with two manually started Django/simulation servers, but does not establish packaged Windows/Linux desktop support. The isolated data structure worked under this Windows Python 3.11.15 audit; this does not validate the complete simulation or current API compatibility.

## OSWorld 2.1

`git ls-remote --tags ... osworld-v2.1` resolved the tag to `3d778a3c9a34a079316f70df023b166700445792`. Initial main checkout was `d9953673daf55381237e058fd9388cc2d74c5538`; the audited checkout now uses the tag. Read README, LICENSE, release manifest, offline release tests, `desktop_env/task_base.py`, `desktop_env/desktop_env.py`, and `desktop_env/controllers/python.py`. Code LICENSE: Apache-2.0; task data, assets, VM images, mocked websites and model weights require their own inventories/terms before any distribution. No assets or images were fetched.

The release manifest pins 108 task files, asset repositories, website source and provider images together. Its `base_commit` is provenance metadata and differs from the actual tag commit: use the resolved tag SHA for code identity. The documented default `require_a11y_tree=True`, accessibility endpoint, Python/bash execution endpoint, Chromium control port and direct evaluator getters are excluded from SOMA runtime. A test harness may prepare/evaluate fixtures independently; the evaluated SOMA agent still receives pixels and sends mouse/keyboard events only. Do not let hidden evaluator state or task answers enter cognition.

Platform evidence: recommended infrastructure is Linux/KVM Docker or AWS with Ubuntu guest images. The source also has other provider adapters, but README says only Docker/AWS images are provided. Python project metadata requires >=3.12, while this audit interpreter is 3.11.15. No native Windows benchmark or Linux VM execution is claimed. The manifest itself notes no complete 108-task evaluation, absent Docker VM boot evidence, and an unmodified Task029 setup timeout; do not rewrite these as passes.

## Actual probes and outputs

Run `python docs/upstream/cognition_smoke.py` from the repository root. It loads selected unchanged AST definitions for Qwen resize and the Generative Agents memory class to avoid unavailable torch/numpy/model dependencies, and imports the dependency-free OSWorld task class. This isolation is deliberately narrower than importing/running the full projects.

```text
Qwen isolated smart_resize: (832, 1504)
Generative Agents isolated memory roundtrip: 1 event
OSWorld BaseTask + v2.1 task hash manifest: PASS, 108 entries
```

The first manifest check against working-tree bytes failed: this host has `core.autocrlf=true`, yielding a worktree SHA256 of `4000c48b50ddbcb1b08f091e6e597dc8302c194f029ff16f6eadd389670ac15b`. Hashing canonical `git show HEAD:<path>` bytes passed the pinned `c54d428329be5ca72742a6becd49ee83cf739df5dea429bba182e1f3f21badfb`. The smoke script uses canonical bytes; this is an audit tooling line-ending issue, not an upstream task-asset validation.

Run the following Node 24.18.1 probe against the actual TypeScript function:

```powershell
node --input-type=module -e "import { isAutoReflectionEnabled } from './.upstream/letta-code/src/reflection-settings.ts'; console.log(JSON.stringify({platform:process.platform,defaultAutoReflection:isAutoReflectionEnabled()})); process.env.LETTA_ENABLE_WINDOWS_AUTO_REFLECTION='1'; console.log(JSON.stringify({optedInAutoReflection:isAutoReflectionEnabled()}));"
```

```text
{"platform":"win32","defaultAutoReflection":false}
{"optedInAutoReflection":true}
```

No model inference, GPU timing, full Letta harness tests, external GUI actions, VM provisioning or full benchmark run occurred. The available Python environment has neither numpy, torch, transformers nor pytest. Firecrawl's setup scrape failed for insufficient credits, so official Hugging Face model-card content was inspected through the web fallback. These are reported limits, not silently substituted runtime passes.

## Minimal SOMA implementation consequence

Use one local persona record, six provenance-bearing memory kinds (episodic, semantic, procedural, social, intentions, reflective), durable goals, an append-only hash-linked event stream, transactional before/after action journal, versioned checkpoints, and app-owned frame files. Recovery reconciles pending actions by fresh pixels; it never blindly replays a pending send/click. Reflection consumes bounded evidence and persists a new confidence-bearing memory. Provider/model selection is configuration, never personality identity. No candidate needs to be a runtime dependency to implement these concepts.
