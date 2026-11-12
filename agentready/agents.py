"""AI crawlers and agents we test against.

Edit this list as vendors add or rename agents. `role` matters for scoring:
blocking a *training* crawler is a legitimate business choice and is not
penalised; blocking *search* or *user* agents makes the store invisible or
unusable in AI answers, and is.
"""
from __future__ import annotations

from dataclasses import dataclass

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
SCANNER_UA = "AgentReadyScanner/0.1 (+https://github.com/; readiness audit; polite)"


@dataclass(frozen=True)
class Agent:
    token: str      # robots.txt user-agent token
    vendor: str
    role: str       # training | search | user
    ua: str | None  # HTTP User-Agent to probe with; None = robots token only


_W = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; {}; +{})"

AGENTS: list[Agent] = [
    # OpenAI
    Agent("GPTBot", "OpenAI", "training", _W.format("GPTBot/1.1", "https://openai.com/gptbot")),
    Agent("OAI-SearchBot", "OpenAI", "search", _W.format("OAI-SearchBot/1.0", "https://openai.com/searchbot")),
    Agent("ChatGPT-User", "OpenAI", "user", _W.format("ChatGPT-User/1.0", "https://openai.com/bot")),
    # Anthropic
    Agent("ClaudeBot", "Anthropic", "training", _W.format("ClaudeBot/1.0", "claudebot@anthropic.com")),
    Agent("Claude-SearchBot", "Anthropic", "search", _W.format("Claude-SearchBot/1.0", "https://anthropic.com")),
    Agent("Claude-User", "Anthropic", "user", _W.format("Claude-User/1.0", "https://anthropic.com")),
    # Perplexity
    Agent("PerplexityBot", "Perplexity", "search", _W.format("PerplexityBot/1.0", "https://perplexity.ai/perplexitybot")),
    Agent("Perplexity-User", "Perplexity", "user", _W.format("Perplexity-User/1.0", "https://perplexity.ai/perplexity-user")),
    # Google
    Agent("Googlebot", "Google", "search", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
    Agent("Google-Extended", "Google", "training", None),
    # Microsoft (Copilot is grounded on Bing)
    Agent("Bingbot", "Microsoft", "search", "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"),
    # Others
    Agent("Applebot-Extended", "Apple", "training", None),
    Agent("Amazonbot", "Amazon", "search", "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot)"),
    Agent("meta-externalagent", "Meta", "training", "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)"),
    Agent("CCBot", "Common Crawl", "training", "CCBot/2.0 (https://commoncrawl.org/faq/)"),
]

# Agents whose HTTP behaviour we actually probe (keeps request volume small).
PROBE_TOKENS = ["OAI-SearchBot", "ChatGPT-User", "Claude-User", "PerplexityBot", "Googlebot"]
