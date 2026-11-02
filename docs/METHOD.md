# How the scores are built

Every Monday a GitHub Action pulls open leaderboard data, fuses it into one catalog and scores every model for every job in [`thalamus/jobs.json`](../thalamus/jobs.json). A personal build (`thalamus update --personal`) runs the same steps with extra opt-in sources and writes to `~/.thalamus/data` instead of the repo. Nothing is hand-ranked. If you disagree with a pick, change the weights in `jobs.json` or teach your own copy with `thalamus feedback`.

## 1. Fetch

Each source is a small module in [`thalamus/sources/`](../thalamus/sources/). A source that fails keeps last week's cached copy and is marked stale in `data/sources.json` and in the weekly changelog. A week where fewer than half the jobs can be ranked is refused and nothing is committed.

## 2. Merge

Sources name the same model differently ("Claude Sonnet 5", "claude-sonnet-5", "Claude 5 Sonnet (Thinking)"). [`merge.py`](../thalamus/merge.py) matches them in this order:

1. a manual override in `data/aliases.json`
2. an OpenRouter id the source already gives
3. same lab and same cleaned-up name
4. same lab and the same set of name words, in any order

The OpenRouter catalog is the backbone, because a model with an OpenRouter id can be called by any tool with one key. Reasoning variants (low, high, xhigh, thinking) stay separate entries, since effort changes both quality and cost. Anything no rule can match becomes its own entry and is listed in `data/unmatched.json` for an alias next week.

## 3. Scale

Benchmarks use different units: Elo points, percentages, seconds, dollars. Inside each job, every metric is rescaled 0-100 across the models that report it: the best model gets 100 and anything at or below the 10th percentile gets 0. Metrics where lower is better (hallucination rate, latency, price, word error rate) are flipped first. Prices, usage volumes and context sizes are put on a log scale first, so a $0.10 vs $0.20 gap counts as much as $10 vs $20.

## 4. Blend

A job is a weighted list of metrics. A model's job score is the weighted average of the metrics it has. Two guards keep thin data from winning:

- **Coverage.** A model needs at least half of the job's available weight to be ranked, and thin coverage costs up to 15% of its score.
- **Quality first.** Price, speed and popularity can never rank a model on their own. It needs at least one quality signal.

## 5. Pick

| Pick | Rule |
|---|---|
| Best | Highest job score |
| Value | Cheapest model whose quality is within 90% of the top quality, from the 10 highest-quality models |
| Budget | Cheapest model whose quality is within 75% of the top quality |
| Fast | Fastest model whose quality is within 85% of the top quality |
| Open weights | Best model you can self-host |

"Quality" here is the job score with price and speed left out, so jobs that already reward low prices (bulk work, structured output) don't count price twice. A pick must be something you can run: models that aren't released, or that no public API serves, still appear in the tables but are never picked.

Some jobs list **essential** signals (speed for instant answers, audio boards for voice and transcription). Without them a job isn't ranked at all that week: an empty table beats a confident wrong one.

## 6. The mixed plan

Most work isn't uniformly hard. Planning, the final review and the decisions are the small share where the top model earns its price. The default mix sends 10% of tokens to Best, 30% to Value and 60% to Budget, and each job's table shows what that costs against sending everything to Best. Change the mix in `score.py` (`DEFAULT_MIX`).

## 7. Your taste on top

Public boards measure the average user. Your verdicts (`thalamus feedback`) live only on your machine in `~/.thalamus/feedback.jsonl` and bend the ranking for you: up to plus or minus 25%, and only after three verdicts on a model can it overturn the public pick. `thalamus scout <job>` suggests an untried strong model for your next low-stakes task, so new releases get tested on your real work.

## Known limits

- Usage rankings (OpenRouter, Kilo) measure popularity, not quality. They carry small weights.
- Arena scores are human preference, which rewards style as well as substance.
- Benchmarks leak into training data. A model's public score can overstate it on your work, which is what the feedback loop is for.
- Media models (image, video, voice) have fewer signals than text models, so their rankings move more week to week.
