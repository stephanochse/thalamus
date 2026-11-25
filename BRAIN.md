# The brain, week of 2026-11-25

Thalamus checks its own inputs every week before it trusts them, keeps a memory of past weeks and writes down here what it learned. The weekly sync rewrites this page. How each check works is at the bottom.

## Picks it held steady

- Research and facts: Claude Opus 5 (High) (within 1.0 of the top score, kept from last week)
- Math and hard reasoning: Claude Fable 5.1 (Max) (within 1.0 of the top score, kept from last week)
- Writing, copy and voice: Gemini 4 Argon (High) (within 1.0 of the top score, kept from last week)
- Reading images, screenshots and documents: Claude Opus 5.5 (High) (within 1.0 of the top score, kept from last week)

## Rising this week

- Nothing moved three places or more (or this is the first week on record).

## How much it trusts each source

Agreement is the rank correlation between one source's view of every job and all the other sources' view, averaged over jobs. Sources measure different things, so the level varies a lot (a hallucination board barely tracks human preference). What counts is a sudden drop below the source's own usual level: that's what a broken feed looks like, and it costs the source weight in every job.

| Source | Agreement this week | Usual | Trust | Last week |
|---|---|---|---|---|
| arena | 0.604 | 0.61 | 1.0 | 1.0 |
| epoch | 0.819 | 0.834 | 1.0 | 1.0 |
| llmstats | 0.572 | 0.588 | 1.0 | 1.0 |
| tau2 | 0.671 | 0.689 | 1.0 | 1.0 |
| vectara | -0.219 | -0.221 | 1.0 | 1.0 |

## Left out this week

- `llmstats.swe_pro`: lost 56 of 56 rows since last week

## Every lab, every job

| Lab | Jobs won | Top 3 in | Strongest at |
|---|---|---|---|
| Google | 15 | 18 | Everyday questions and chat (Gemini 4 Carbon (High)), 100% of the top score |
| Anthropic | 9 | 19 | Research and facts (Claude Opus 5 (Max)), 100% of the top score |
| OpenAI | 4 | 7 | Image generation (GPT-Image-2.6 Sunburst (Medium)), 100% of the top score |
| Alibaba (Qwen) | 2 | 4 | Following instructions and structured output (Qwen3.8 Max (xHigh)), 100% of the top score |
| Meta | 1 | 2 | Video from text (Muse Video), 100% of the top score |
| Zhipu (Z.ai) | 1 | 1 | Bulk work at the lowest price (GLM 5.3 Flash), 100% of the top score |
| DeepSeek | 0 | 1 | Bulk work at the lowest price (DeepSeek V4.1 Flash (Max)), 100% of the top score |
| ByteDance | 0 | 1 | Video editing (Dreamina Seedance 2.5), 98% of the top score |
| Moonshot AI | 0 | 1 | Business, finance and analysis (Kimi K3.1 Pro (Max)), 96% of the top score |
| hidream | 0 | 1 | Animate an image into video (HiDream-O1-Video-1.0), 91% of the top score |
| xAI | 0 | 1 | Animate an image into video (Grok Imagine Video 1.5), 90% of the top score |
| Microsoft | 0 | 1 | Image editing (MAI-Image-2.7), 89% of the top score |
| Xiaomi | 0 | 0 | Backends, SaaS and system design (MiMo-V2.6-Pro), 93% of the top score |
| Black Forest Labs | 0 | 0 | Animate an image into video (FLUX 3 Video), 89% of the top score |
| Tencent | 0 | 0 | Bulk work at the lowest price (Hy3), 88% of the top score |
| SpaceXSI | 0 | 0 | Translation and other languages (Grok 4.20 (Reasoning)), 86% of the top score |

## What it can't judge well yet

Strong models ranked on far less evidence than the others in the same table, usually because they're new and most leaderboards haven't tested them. Try them on low-stakes work (`thalamus scout <job>`) and file a verdict.

- Claude Fable 5.2 (xHigh): #1 for games, 3d and interactive scenes on 2 signals (59% of the evidence)
- Claude Opus 5.5 (Max): #2 for games, 3d and interactive scenes on 2 signals (59% of the evidence)
- Gemini 4 Neon (High): #6 for strategy, plans and decisions on 4 signals (76% of the evidence)
- Claude Opus 5.5 (High): #2 for decks, slides and one-pagers on 4 signals (71% of the evidence)
- Gemini 4 Hydrogen (High): #8 for math and hard reasoning on 2 signals (80% of the evidence)
- Gemini 3.8 Flash (High): #9 for math and hard reasoning on 2 signals (80% of the evidence)
- Claude Fable 5.2 (Max): #6 for decks, slides and one-pagers on 4 signals (71% of the evidence)
- Muse Wonder (Max): #15 for math and hard reasoning on 2 signals (80% of the evidence)
- Claude Fable 5.1 (Max): #1 for long documents and big codebases on 1 signal (67% of the evidence)
- Gemini 4 Neon (xHigh): #7 for websites, ui and screenshot-to-code on 1 signal (53% of the evidence)
- Claude Opus 5 (High): #2 for long documents and big codebases on 1 signal (67% of the evidence)
- GPT-6.2 Astra (Max): #8 for websites, ui and screenshot-to-code on 1 signal (53% of the evidence)

## Names it couldn't match

Models a source scored that the brain couldn't tie to a callable model. An entry in `data/aliases.json` merges them next week.

- Muse Spark (Meta): 37 signals, id `arena:muse-spark`
- Gemini 3 Pro (Google): 49 signals, id `arena:gemini-3-pro`
- GPT-5.2 Chat (OpenAI): 19 signals, id `arena:gpt-5.2`
- Grok 4.20 Beta 1 (xAI): 17 signals, id `arena:grok-4.20-1`
- GPT-5.5 Instant (OpenAI): 31 signals, id `arena:gpt-5.5-instant`
- ERNIE 5.1 (Baidu): 17 signals, id `arena:ernie-5.1`
- MiMo-V2.5-Pro (Xiaomi): 35 signals, id `arena:mimo-v-2.5-pro`
- Grok 4.1 (xAI): 20 signals, id `arena:grok-4.1`
- Qwen3.5-Max-Preview (Alibaba (Qwen)): 16 signals, id `arena:qwen-3.5-max`
- Qwen3.6-Max-Preview (Alibaba (Qwen)): 19 signals, id `arena:qwen-3.6-max`
- Dola Seed 2.0 Pro (ByteDance): 19 signals, id `arena:dola-seed-2.0-pro`
- GPT-5.3 Chat (OpenAI): 18 signals, id `arena:gpt-5.3`

## Community verdicts

None yet. Anyone can add one: open a **Model verdict** issue in this repo, or run `thalamus feedback <job> <model> good --share`.

## How the checks work

- **Quarantine.** A metric whose rankings correlate under 0.5 with last week's, or that lost more than 50% of its rows, is left out for the week.
- **Trust.** A source whose agreement with the others falls more than 0.2 below its usual level loses weight, down to 0.5 at most, moving halfway each week. Steady sources keep full weight however different their view.
- **Steady picks.** A new best pick has to beat last week's by more than 1.0 points.
- **Memory.** The top 15 for every job, for 26 weeks, in `data/history.json`.
- **Community.** Verdicts filed as GitHub issues, counted once per person per model, from accounts at least six months old. They can't change the best pick.
