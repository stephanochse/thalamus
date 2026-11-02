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
5. a trailing effort word on a plain name ("DeepSeek V4 Pro Max", "Grok 4.20 Reasoning") lands on that model's effort variant. "Max" counts as effort only on a reasoning model, so "Qwen3.8 Max" stays a model of its own

The OpenRouter catalog is the backbone, because a model with an OpenRouter id can be called by any tool with one key. Reasoning variants (low, high, xhigh, thinking) stay separate entries, since effort changes both quality and cost. Anything no rule can match becomes its own entry and is listed in `data/unmatched.json` for an alias next week.

## 3. Scale

Benchmarks use different units: Elo points, percentages, seconds, dollars. Inside each job, every metric is rescaled 0-100 across the models that report it: the best model gets 100 and anything at or below the 10th percentile gets 0. Metrics where lower is better (hallucination rate, latency, price, word error rate) are flipped first. Prices, usage volumes and context sizes are put on a log scale first, so a $0.10 vs $0.20 gap counts as much as $10 vs $20.

## 4. Blend

A job is a weighted list of metrics. A model's job score is the weighted average of the metrics it has. Two guards keep thin data from winning:

- **Coverage.** A model needs at least half of the job's available weight to be ranked, and thin coverage costs up to 15% of its score.
- **Quality first.** Price, speed and popularity can never rank a model on their own. It needs at least one quality signal.
- **Claims.** Benchmarks the labs report about their own models (llm-stats marks almost all of them self-reported) carry `"claim": true` in `jobs.json`. They add to a model's score and coverage at small weights, but they don't count toward the coverage bar, so a model that independent boards tested isn't pushed out by one that only has launch-day numbers.

Before blending, each metric's weight is multiplied by its source's trust (section 8), and quarantined metrics are left out.

## 5. Pick

| Pick | Rule |
|---|---|
| Best | Highest job score |
| Value | Cheapest model whose quality is within 90% of the top quality, from the 10 highest-quality models |
| Budget | Cheapest model whose quality is within 75% of the top quality |
| Fast | Fastest model whose quality is within 85% of the top quality |
| Open weights | Best model you can self-host |
| Other lab | Best model from a different lab than the best pick, within 80% of its quality: the second opinion |

Every job also lists **every lab's best callable model** with its rank and its share of the top score, in `data/routes.json` (`labs`), in ROUTES.md and through `thalamus top <job> --labs`. A lab that wins nothing this week still shows how close it came.

"Quality" here is the job score with price and speed left out, so jobs that already reward low prices (bulk work, structured output) don't count price twice. A pick must be something you can run: models that aren't released, or that no public API serves, still appear in the tables but are never picked.

Some jobs list **essential** signals (speed for instant answers, audio boards for voice and transcription). Without them a job isn't ranked at all that week: an empty table beats a confident wrong one.

## 6. The mixed plan

Most work isn't uniformly hard. Planning, the final review and the decisions are the small share where the top model earns its price. The default mix sends 10% of tokens to Best, 30% to Value and 60% to Budget, and each job's table shows what that costs against sending everything to Best. Change the mix in `score.py` (`DEFAULT_MIX`).

## 7. Your taste on top

Public boards measure the average user. Your verdicts (`thalamus feedback`) live only on your machine in `~/.thalamus/feedback.jsonl` and bend the ranking for you: up to plus or minus 25%, and only after three verdicts on a model can it overturn the public pick. `thalamus scout <job>` suggests an untried strong model for your next low-stakes task, so new releases get tested on your real work.

## 8. The brain: self-checks between weeks

[`brain.py`](../thalamus/brain.py) runs before scoring and writes what it found to [BRAIN.md](../BRAIN.md). Every step is plain arithmetic, so the same data always gives the same result.

- **Quarantine.** Each metric is compared with last week's `models.json`. A rank correlation under 0.5 for the models both weeks share, or fewer than half last week's rows, means the feed probably broke, and the metric sits out the week.
- **Trust.** For every job, models are ranked once by one source alone and once by all the other sources, and the two rankings are correlated (leave one out), then averaged over jobs. Sources measure different things, so the level says little: a hallucination board barely tracks human preference and is still worth having. Each source keeps its own usual level (a slow running average). A week where agreement falls more than 0.2 below that usual level, the way a parser reading the wrong column would, lowers the source's weight by 1.5 x the extra drop, never below 0.5, moving halfway each week, and that week isn't folded into the usual level. Steady sources keep full weight.
- **Steady picks.** A new best pick has to beat last week's by more than 1.0 point, or last week's pick stays and is marked as held.
- **Memory.** `data/history.json` keeps the top 15 per job for 26 weeks. ROUTES.md shows who moved.
- **Blind spots.** Strong models ranked on far less evidence than their peers in the same table are listed as ones to scout.
- **Community verdicts.** Anyone can file a "Model verdict" issue. The Action counts one vote per person per model (most recent wins) from accounts at least 180 days old when they voted, and ignores bots, issues closed as not planned or duplicate, and issues a maintainer labels `spam`. It stores only the counts in `data/community.json`. A model needs five different people before its score moves, then by `1 + 0.2 x (belief - 0.5) x n / (n + 20)`, never more than 10%. Votes change ranks and the value, budget and other-lab picks; the best pick always comes from the public evidence alone. If more verdict issues exist than one run can read, the run keeps last week's counts instead of counting a partial window.

## Known limits

- Most llm-stats benchmark scores are self-reported by the labs. They're treated as claims, at small weights.
- Vectara measures staying on source when summarising, not closed-book knowledge, and small, terse models tend to do well on it. It carries a weight of 1 or less and can't rank a model on its own.
- Trust reacts to sudden drops in agreement, so a source that is right on the week everyone else changes course loses some weight for a while. The floor (0.5) keeps that cost small.
- Arena scores are human preference, which rewards style as well as substance.
- Benchmarks leak into training data. A model's public score can overstate it on your work, which is what the feedback loop is for.
- Media models (image, video, voice) have fewer signals than text models, so their rankings move more week to week.
