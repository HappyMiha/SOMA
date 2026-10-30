# Upstream evaluation — 2026-10-30

All 12 repositories in specification §2 (OpenAdapt counts as two) were shallow
cloned and inspected before implementation. No upstream runtime or code is
vendored. The minimal reusable set consists of architectural patterns: screenshot
feedback, multi-step visual planning, semantic demonstration trajectories,
episodic recall/reflection and a pinned external benchmark.

The audit is split into primary evidence reports, each containing exact SHA,
LICENSE, current module paths, platform evidence, excluded bypasses and concrete
PoC commands/results:

* [GUI execution](upstream/gui.md): OthersideAI/self-operating-computer,
  simular-ai/Agent-S, bytedance/UI-TARS-desktop, showlab/computer_use_ootb.
* [Learning](upstream/learning.md): showlab/ShowUI-Aloha,
  OpenAdaptAI/OpenAdapt, OpenAdaptAI/openadapt-capture, showlab/ShowUI.
* [Cognition and benchmark](upstream/cognition.md): QwenLM/Qwen3-VL,
  letta-ai/letta-code, joonspk-research/generative_agents, xlang-ai/OSWorld-V2.

Candidate PoCs are isolated code/static probes, not execution of their entire
desktop agents. Their limitations are explicit in each report. SOMA's separate
live body fixture is recorded in TEST_RESULTS.md. Importing an entire runtime
would introduce rejected paths including exec/eval, clipboard, DOM/UIA, UNO,
shell tools, app metadata or filesystem tools. Adaptation means reimplementing
the documented idea through SOMA's fixed port, not enabling those tools.

Native Wayland support is not established by any reused runtime. OSWorld-V2 is
pinned to tag osworld-v2.1; source manifest probes do not count as benchmark task
passes. Model code and weight licenses were inspected separately where possible;
no weight distribution is included in this build.
