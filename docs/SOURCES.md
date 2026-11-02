# Sources

Thalamus only reads data its publishers allow to be read this way: official APIs and open datasets. It never scrapes a website whose terms forbid it, even when the numbers sit right there in the page. And it only publishes what each source allows to be republished.

## The public weekly build

These run in the GitHub Action and feed the committed `data/` and `ROUTES.md`.

| Source | What it adds | How it's read | Terms |
|---|---|---|---|
| [OpenRouter](https://openrouter.ai) | The callable catalog: ids, prices, context windows, modalities, release dates | Documented public API `/api/v1/models`, no key | Public API |
| [Arena](https://arena.ai) | Human preference: overall, coding, hard prompts, creative writing, math, instruction following, multi-turn, expert, non-English, legal, business, healthcare, factuality, web development, screenshot-to-web, vision, documents, search, agents, image (overall, text rendering, photoreal, design), image editing, video, image-to-video, video editing | Arena's open dataset on Hugging Face, `lmarena-ai/leaderboard-dataset` | CC BY 4.0 |
| [llm-stats](https://llm-stats.com) | Category indexes: legal, finance, agents, tool calling, long context, structured output and more | Open JSON API at `api.llm-stats.com` | Reuse, including commercial, allowed with attribution. Many underlying scores are self-reported by vendors, so they carry small weights |
| [Epoch AI](https://epoch.ai) | Epoch Capabilities Index and Epoch's own SWE-bench Verified runs | `benchmark_data.zip` | CC BY 4.0 for Epoch's own data |

## Personal builds (opt-in, never published)

`python -m thalamus update --personal --with aa,epoch_external,benchlm,eqbench` adds any of these and writes to `~/.thalamus/data`. Routing uses that folder automatically while it's at least as fresh as the public data.

| Source | What it adds | Why it's personal-only |
|---|---|---|
| [Artificial Analysis](https://artificialanalysis.ai) (`aa`) | Intelligence Index, capability indexes (strategy and operations, finance and accounting, legal, healthcare, engineering, economics), speed and latency, Elo for image, editing, video, speech and transcription | Official API with a free key (100 requests a day; a run uses about 10). Attribution is required on every tier, the free tier doesn't grant redistribution, and their terms ask for written consent before the data powers a public model-selection product |
| Epoch's re-hosted external benchmarks (`epoch_external`) | Terminal-Bench, METR time horizons, ARC-AGI-2, Humanity's Last Exam, Fiction.LiveBench, Aider Polyglot | Epoch notes that externally sourced data keeps its original licensing |
| [BenchLM](https://benchlm.ai) (`benchlm`) | Composite category scores | CC BY-NC 4.0 |
| [EQ-Bench](https://eqbench.com) (`eqbench`) | Creative writing Elo and a "slop" score | No published license or terms for the data |

Without these, three jobs can't be ranked: instant answers (needs speed data), voiceover and transcription (need audio boards). They show as "not enough data" in the public tables.

## Not used, on purpose

| Site | Why |
|---|---|
| Artificial Analysis website pages | Its terms of use forbid scraping. The API above is the supported route |
| arena.ai website | Its terms forbid automated access and it blocks bots. The open dataset above is the supported route |
| OpenRouter rankings pages | Its terms forbid scraping the site. The rankings also measure token volume, not quality |
| Kilo Code leaderboard | Its terms forbid scrapers |

## Setting up the Artificial Analysis key (personal builds)

1. Create a free account at [artificialanalysis.ai](https://artificialanalysis.ai) and create an API key.
2. Set `ARTIFICIAL_ANALYSIS_API_KEY` in your environment, or put `ARTIFICIAL_ANALYSIS_API_KEY=...` in `~/.thalamus/env`.
3. Run `python -m thalamus update --personal --with aa`. Credit Artificial Analysis wherever you show the results.

Don't add the key to the public GitHub Action: a public repo republishing AA-derived rankings needs their written consent first.

## Adding a source

Write a module in `thalamus/sources/` with `NAME`, `URL`, `ATTRIBUTION`, `REDISTRIBUTE`, `PREFIX` (if its metric ids don't start with the module name) and a `fetch()` that returns records (shape in `sources/__init__.py`). Add it to `SOURCES` in `update.py` only if its terms allow automated access and republishing; otherwise add it to `OPTIONAL`. Then give its metrics weights in `jobs.json`. Say what the terms are, with a link, in the module docstring.
