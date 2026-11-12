# Agent Ready

A readiness scanner for agentic commerce. Give it a store's domain and it checks
how a shopping agent experiences the site: whether agents can get in, whether the
store speaks UCP, whether there is a store-side agent to talk to, whether answer
engines can understand the catalogue, whether content exists without JavaScript,
and whether an agent can actually reach checkout.

Output: a self-contained HTML report (maturity tier, score, prioritised fixes,
competitor comparison, evidence for every finding) plus a JSON file.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[browser,dev]'
playwright install chromium          # optional; without it browser checks show "Not run"

agentready scan client.com --vs rival-one.com --vs rival-two.com
open reports/client.com.html
```

Useful options:

| Option | What it does |
|---|---|
| `--vs DOMAIN` | Add a competitor (repeatable). Shown on the ladder and in a comparison table. |
| `--product-url URL` | Scan these product pages instead of auto-discovering (repeatable). |
| `--category-url URL` | Same, for a category page. |
| `--max-products N` | How many product pages to sample (default 4). |
| `--no-browser` | Skip headless-browser checks (faster). |
| `--delay S` | Seconds between requests to one site (default 0.6). |
| `--name NAME` | Report file name. |

## Run a full scan for a new site (step by step)

Use this when you are starting from a fresh machine or terminal. Only scan sites
you have a reason to assess.

### One-time setup

Requires Python 3.10 or newer (`python3 --version`). On macOS: `brew install python@3.12`.

```bash
git clone https://github.com/SandmanExtraordinaire/agentready.git
cd agentready
```

```bash
/opt/homebrew/bin/python3.12 -m venv .venv      # or: python3 -m venv .venv
source .venv/bin/activate
```

```bash
pip install --upgrade pip
pip install -e '.[browser]'                      # add ,dev to also run the tests
playwright install chromium                      # headless browser for the journey checks
```

### Every new terminal tab

The virtual environment only lasts for the tab it was activated in.

```bash
cd agentready
source .venv/bin/activate
```

The prompt now starts with `(.venv)`.

### Scan a site

```bash
agentready scan newsite.com
```

With competitors, for comparison on the maturity ladder:

```bash
agentready scan newsite.com --vs rival-one.com --vs rival-two.com
```

Faster run without the browser checks, or a named report:

```bash
agentready scan newsite.com --no-browser --name newsite-2026-11
```

Scan specific pages instead of auto-discovering them:

```bash
agentready scan newsite.com \
  --product-url https://newsite.com/products/example-shoe \
  --category-url https://newsite.com/collections/shoes
```

### Read the results

```bash
open reports/newsite.com.html        # macOS; use xdg-open on Linux
```

`reports/newsite.com.json` holds the same data for further processing. Reports
are git-ignored and must never be committed.

### Run the tests (optional)

```bash
pip install -e '.[browser,dev]'
pytest
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `agentready: command not found` or `playwright: command not found` | The venv is not active in this tab. Run `source .venv/bin/activate` from the project folder. |
| `File "setup.py" or "setup.cfg" not found` | pip is too old. Run `pip install --upgrade pip`, then retry. |
| Python version error on install | Python is older than 3.10. Recreate the venv with Python 3.10+. |
| Browser checks show "Not run" | Run `playwright install chromium`, or ignore if you passed `--no-browser`. |

## What it checks

| Layer | Checks | Weight |
|---|---|---|
| Agent access | robots.txt rules for 15 AI agents (training crawlers not penalised); bot walls compared browser vs agent | 25 |
| Commerce protocols | UCP profile valid against its declared release; checkout/cart declared; endpoints live (MCP handshake); version current; ACP signals (inferred, unscored) | 20 |
| Agent-to-agent | A2A agent card; MCP server with tool list; on-site assistant (unscored) | 10 |
| AI discoverability | Product markup, core offer fields, GTIN/brand, return & shipping policies, ratings, price consistency, Organization, sitemap, llms.txt, page metadata | 20 |
| Works without JavaScript | Name/price in raw HTML; Product markup not JS-injected (browser) | 10 |
| Task completion | Cart reachable by assistant agents; add to cart; reach checkout (browser) | 15 |

### Maturity tiers

Tiers are gates, not score bands. A store reaches a tier only when it meets that
tier and every tier below it: **Invisible → Readable → Discoverable →
Transactable → Agent-native**. Conditions live in `agentready/rubric.yaml`.

### Changing weights or tiers

Edit `agentready/rubric.yaml`. No code changes needed; finding ids there match
the ids in the checks.

### Adding a check

Add a function to the right file in `agentready/checks/`, decorate it with
`@check("<layer>")`, return a list of `Finding`s, and give its id a weight in
`rubric.yaml`. Add a case to the fake store in `tests/conftest.py`.

## Running from GitHub (no laptop needed)

- **Actions → Scan a store → Run workflow.** Enter the domain (and competitors).
  The report is attached to the run as an artifact for 14 days. It is never
  committed or published.
- **Tests** run on every push.
- **Sync UCP schemas** runs weekly and opens a pull request when UCP ships a new release.
- **Publish site** deploys `docs/` (landing page + synthetic sample report) to
  GitHub Pages. Enable once under Settings → Pages → Source: GitHub Actions.

## Client data rule

The repo is public. Client reports live only in `reports/` (git-ignored) or in
Actions artifacts. Never commit a client name, URL or report. `docs/` contains
synthetic data only; rebuild the sample with `python scripts/make_sample_report.py`.

## Honest limits

- Bot-protection results come from AI agents' user-agent strings sent from your
  IP. Real agents may be verified by IP or signature, so these are marked inferred.
- ACP integrations are private; the scan reports signals only.
- AI-surface visibility (does ChatGPT/Gemini/Perplexity cite the brand) needs API
  keys and is on the roadmap.
- Run scans only on sites you have a reason to assess, at the default polite pace.

## Repo layout

```
agentready/
  cli.py            command line
  scanner.py        orchestrates one scan
  discover.py       finds home, category, product, cart pages
  http.py           polite cached fetcher
  agents.py         AI agent list (edit as vendors change)
  ucp_schema.py     UCP profile validation, per release
  mcp.py            read-only MCP handshake
  browser.py        optional Playwright wrapper
  checks/           one file per layer
  rubric.yaml       weights and tiers
  scoring.py        scores, tiers, fix priority
  report.py         HTML + JSON output
  templates/        report template
  schemas/ucp/      vendored UCP schemas, one folder per release
scripts/            schema sync, sample report
tests/              offline fake stores + tests
docs/               GitHub Pages site (synthetic data only)
```

## Roadmap

1. Run against 5–10 real stores you know well; tune weights and fix false readings.
2. Re-scan history: compare a store against its own previous scan.
3. AI-surface visibility module (needs API keys).
4. Non-probe evidence for the readiness eval: interview answers and artifact review, scored on the same rubric.
5. Optional hosted version (FastAPI + Playwright container) if clients want self-serve.
