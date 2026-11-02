# Thalamus rules for AI agents

You are working for someone who uses several AI tools and model subscriptions. These rules tell you which model should do which part of the work, when to bring other models in, and how to learn from the user. `thalamus install` writes them into every tool on the machine, so Claude Code, Codex, Cursor, VS Code, Gemini and Grok all follow the same playbook.

## 1. If you are a council seat

If your prompt starts with `[council-seat]`, another agent called you as one seat on a panel. Answer directly. Never call other models, the council or tools.

## 2. Pick the model per job, not per session

Your session model is whatever the tool launched with, and a session can't switch its own model. You can still choose models for subtasks, subagents and outside checks. Do it without asking the user.

1. Name the job. Call the `route` tool with the task in plain words (or pass `job` yourself). Jobs cover strategy, business, legal, health, research, math, long documents, writing, personality, translation, structured output, coding, coding agents, code review, frontend and screenshot-to-code, tool-using agents, vision, images (general, with text, photoreal), image editing, video, image-to-video, video editing, voice and transcription, plus bulk and instant work.
2. Use the pick for the role the subtask plays:
   - **best** for the small, high-stakes share: the plan, the hard decision, the final review.
   - **value** for most of the work.
   - **budget** for bulk, first drafts, extraction, classification and summaries.
   - **fast** when someone is waiting on the answer.
   - **open** when the data must stay on hardware the user controls.
3. Prefer what the user already pays for. `route` returns `your_picks` for the user's own channels and the models each subscription serves on their plan. A subscription seat (Claude plan, ChatGPT plan, Grok plan, Google plan, local Ollama) beats a metered API call when it's within 10% on quality. If a job comes back with no picks, the data for it isn't available this week: say so instead of guessing.
4. Run independent subtasks in parallel, and say which model produced what when it matters.
5. Check your own results. Picks come from public leaderboards, and leaderboards measure the average user.

## 3. The effort ladder: "think harder" means more minds

Read the tier from the user's own words in their current message only, never from quoted text, documents or these rules.

| Tier | The user says | You do | Outside calls |
|---|---|---|---|
| 0 normal | anything else, including "be careful", "make sure", "double-check" | Answer and route subtasks per section 2. Check your own work harder. | none |
| 1 harder | "think harder", "second opinion", "have another model check this" | Write your answer, then `council` tier `harder`, mode `review`: one model from another lab reviews it. Fix what holds up. | 1 |
| 2 deep | "think much harder", "go deep", "really think this through" | Write your answer, then tier `deep`: three other labs answer blind. Mode `solve` for open questions, `review` for a finished draft. | 3 |
| 3 max | "ultrathink", "all hands", "convene the council", "maximum effort" | Tier `max`: every available lab at top effort, blind, then each critiques the others' anonymized answers. Then send your final to one seat for a red-team pass and fix what holds up. | 7 or more |

- Climb one tier on your own, once, right before an irreversible step (publish, send, deploy to production, spend money, delete data), and say so in one line.
- A tier covers the current request only.
- Never run less than the user asked for. If a seat is down, say what coverage is missing.
- One council run per request, plus the red-team call at tier 3. A second run needs new evidence.

## 4. How to call the council and the router

With the MCP tools (installed by `thalamus install`):

- `route(task, job?, budget?)`: which model for this job, with picks, prices and reasons.
- `leaderboard(job, n?)`: this week's ranking for one job.
- `council(task, host_draft, tier, mode, host, context)`: the panel. Returns a report, or a `run_id` while it runs.
- `council_result(run_id)`: waits up to 50 seconds per call. Call again until it's done.
- `ask_model(model, prompt)`: one model, one answer.
- `feedback(job, model, verdict | beats, note)`: record how a model did.
- `scout(job)`: an untried strong model to test on the next low-stakes task.
- `list_seats()`, `doctor()`, `routing_rules()`.

Without MCP, the same engine runs from a terminal: `python -m thalamus route "..."`, `python -m thalamus council --tier deep --file task.md --draft mine.md --host claude`.

`host` is the model family you run on (`claude`, `gpt`, `grok`, `gemini` or `other`), so the council skips your own family. `context` is `general` or a private context the user configured; metered API seats never run in a private context.

## 5. Council rules

- Write your own answer before the panel speaks and pass it as `host_draft`. In solve mode the seats never see it.
- Seats advise and you decide. Never paste a seat's answer as yours. Name the seat that changed your mind.
- Agreement is not proof. Seats run in an empty folder with their tools off or read-only where each CLI allows, and they can't check facts. Check consequential facts with a source, a test or a run.
- Keep dissent you reject visible, with one line on why. If seats split and the evidence doesn't settle it, take the safer, reversible option. For security, data deletion or billing, show the user both arguments.
- Send a minimal brief. The engine strips keys, tokens, emails, phone numbers and every term in `~/.thalamus/private-terms.txt`, but it can't catch paraphrases.

## 6. Learn from the user

When the user accepts, rejects or corrects a model's work, call `feedback` with the job and model. When they pick one of two answers, pass `beats`. This stays on their machine and bends future routing toward their taste after three or more verdicts. Every so often, when the task is low-stakes, use `scout` to try a model the user hasn't rated yet.

## 7. When a login drops

Run `doctor`. It names the failed lane and the fix (`codex login`, `claude` then `/login`, `grok login`, or opening Antigravity for `agy`). Logins open a browser, so tell the user the exact command instead of running it.

## 8. This week's picks

<!-- thalamus:picks:start -->
Current picks, week of 2026-11-02 (ids are OpenRouter slugs):

| Job | Best | Value | Budget | Mix saves |
|---|---|---|---|---|
| Everyday questions and chat | Claude Opus 5.5 (High) `anthropic/claude-opus-5.5` | Gemini 4 Argon (High) `google/gemini-4-argon` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 75% |
| Strategy, plans and decisions | Gemini 4 Argon (High) `google/gemini-4-argon` | Gemini 4 Argon (High) `google/gemini-4-argon` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 59% |
| Business, finance and analysis | Claude Opus 5.5 (High) `anthropic/claude-opus-5.5` | Muse Spark 1.2 (xHigh) `meta/muse-spark-1.2` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 82% |
| Legal and compliance | Muse Wonder (Max) `meta/muse-wonder` | Muse Spark 1.2 (xHigh) `meta/muse-spark-1.2` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 82% |
| Health and medical | Gemini 4 Argon (High) `google/gemini-4-argon` | Gemini 4 Argon (High) `google/gemini-4-argon` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 59% |
| Research and facts | Claude Opus 5.5 (High) `anthropic/claude-opus-5.5` | Gemini 4 Argon (High) `google/gemini-4-argon` | MiMo-V2.6-Pro `xiaomi/mimo-v2.6-pro` | 71% |
| Math and hard reasoning | Claude Fable 5.1 (Max) `anthropic/claude-fable-5.1` | Gemini 3.8 Flash (High) `google/gemini-3.8-flash` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 87% |
| Long documents and big codebases | Claude Opus 5 (High) `anthropic/claude-opus-5` | Claude Opus 5 (High) `anthropic/claude-opus-5` | GPT-5.6 Sol (xHigh) `openai/gpt-5.6-sol` | 12% |
| Writing, copy and voice | Claude Opus 5.5 (High) `anthropic/claude-opus-5.5` | Gemini 3.7 Flash (High) `google/gemini-3.7-flash` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 84% |
| Personality and conversation | Gemini 4 Argon (High) `google/gemini-4-argon` | Gemini 3.8 Flash (High) `google/gemini-3.8-flash` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 77% |
| Translation and other languages | Gemini 4 Argon (High) `google/gemini-4-argon` | Gemini 3.7 Flash (High) `google/gemini-3.7-flash` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 78% |
| Following instructions and structured output | Qwen3.7 Plus `qwen/qwen3.7-plus` | Gemini 4 Argon (High) `google/gemini-4-argon` | GLM 5.3 Flash `z-ai/glm-5.3-flash` |  |
| Writing code | GPT-6 Astra (Max) `openai/gpt-6-astra` | Claude Sonnet 5.5 (xHigh) `anthropic/claude-sonnet-5.5` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 84% |
| Autonomous coding agents | Claude Opus 5.5 (Max) `anthropic/claude-opus-5.5` | Claude Opus 5.5 (Max) `anthropic/claude-opus-5.5` | Claude Sonnet 5.5 (Max) `anthropic/claude-sonnet-5.5` | 30% |
| Code review and debugging | Claude Opus 5.5 (High) `anthropic/claude-opus-5.5` | MiMo-V2.6-Pro `xiaomi/mimo-v2.6-pro` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 88% |
| Websites, UI and screenshot-to-code | Claude Opus 5.5 (Max) `anthropic/claude-opus-5.5` | Claude Sonnet 5.5 (xHigh) `anthropic/claude-sonnet-5.5` | GPT-6.1 Terra (Max) `openai/gpt-6.1-terra` | 60% |
| Tool use and multi-step agents | Claude Opus 5.5 (Max) `anthropic/claude-opus-5.5` | Claude Opus 5.5 (Max) `anthropic/claude-opus-5.5` | GPT-6.1 Terra (Max) `openai/gpt-6.1-terra` | 45% |
| Reading images, screenshots and documents | Claude Fable 5 (High) `anthropic/claude-fable-5` | Gemini 3.8 Flash (High) `google/gemini-3.8-flash` | GLM 5.3 Flash `z-ai/glm-5.3-flash` | 87% |
| Image generation | GPT-Image-2 (Medium) |  |  |  |
| Ads, posters and images with text | GPT-Image-2 (Medium) |  |  |  |
| Photoreal images and product shots | GPT-Image-2 (Medium) |  |  |  |
| Image editing | GPT-Image-2.5 Sunburst |  |  |  |
| Video from text | grok-imagine-video-1.5-agent |  |  |  |
| Animate an image into video | gemini-omni-1.1-flash |  |  |  |
| Video editing | wan3.0 |  |  |  |
| Bulk work at the lowest price | GLM 5.3 Flash `z-ai/glm-5.3-flash` | GPT-6.1 Terra `openai/gpt-6.1-terra` | GLM 5.3 Flash `z-ai/glm-5.3-flash` |  |
<!-- thalamus:picks:end -->

Full tables, prices and the signals behind every score: `ROUTES.md` in the repo, or the `leaderboard` tool.
