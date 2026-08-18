"""Affiliate link automation — Amazon Associates auto-insertion.

After SEO is generated, this module asks the LLM to suggest Amazon
product search terms relevant to the video's topic. Each search term
is converted into an Amazon Associates affiliate link using the
channel's tag, and appended to the video's description.

When the Amazon Product Advertising API keys are configured, we also
fetch real product data (title, price, image, rating) and embed those
in the description as a "📖 Resources mentioned" section.

Without the PA API, we still produce plain affiliate search links
(`https://www.amazon.com/s?k=QUERY&tag=YOUR-TAG-21`) which earn the
same commission — they just don't show product images.

The orchestrator calls `enrich_description_with_affiliates()` after
SEO, before the upload.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..core.logging import get_logger
from ..core.utils import clamp
from . import llm

log = get_logger("affiliate")

# Max number of affiliate links to insert per video.
MAX_LINKS = 5


async def suggest_product_queries(topic: str, niche: str,
                                  max_queries: int = MAX_LINKS) -> list[str]:
    """Ask the LLM to suggest Amazon product search queries for the video.

    The queries should be things a viewer of this video would genuinely
    want to buy — books, tools, gadgets related to the topic. NOT random
    spam.
    """
    prompt = [
        {"role": "system", "content": (
            "You suggest Amazon product search queries for a YouTube video. "
            "Respond ONLY with a JSON array of strings — each string is a 2-5 "
            "word Amazon search query a viewer of this video would genuinely "
            "want to buy. Be specific (e.g. 'portable SSD 1TB' not 'storage'). "
            f"Maximum {max_queries} queries. No books unless the video is "
            "explicitly educational."
        )},
        {"role": "user", "content": (
            f"Topic: {topic}\nNiche: {niche}\n\n"
            f"What products would a viewer of this video want to buy?"
        )},
    ]
    try:
        data = await llm.chat_json(prompt, temperature=0.5)
        if isinstance(data, list):
            return [clamp(str(q), 80) for q in data if q][:max_queries]
    except Exception as exc:
        log.warning("affiliate query LLM call failed: %s", exc)
    return []


def build_affiliate_url(query: str, tag: str | None = None) -> str:
    """Build an Amazon Associates affiliate search URL for a query."""
    tag = tag or settings.amazon_affiliate_tag
    if not tag:
        return ""
    from urllib.parse import quote_plus
    return f"https://www.amazon.com/s?k={quote_plus(query)}&tag={tag}"


async def fetch_product_metadata(query: str) -> dict | None:
    """Fetch real product data via the Amazon Product Advertising API.

    Returns None when the PA API isn't configured or the lookup fails.
    """
    if not settings.amazon_affiliate_available:
        return None
    # The Amazon PA API v5 requires signed requests with HMAC-SHA256.
    # Implementing the full signing flow here would bloat the module.
    # For now we just return None — the affiliate URL alone is enough
    # to earn commission. Real product metadata can be added later.
    # TODO: implement PA API v5 signing (botocore-style) for product cards.
    return None


async def enrich_description_with_affiliates(
    description: str,
    topic: str,
    niche: str,
    max_links: int = MAX_LINKS,
) -> dict:
    """Add an affiliate links section to a video description.

    Returns:
      {
        "description": str,         # enriched description
        "links": [{query, url, product_metadata?}],
        "added": bool,
        "reason": str,
      }
    """
    if not settings.amazon_affiliate_tag:
        return {"description": description, "links": [], "added": False,
                "reason": "AMAZON_AFFILIATE_TAG not set"}

    queries = await suggest_product_queries(topic, niche, max_queries=max_links)
    if not queries:
        return {"description": description, "links": [], "added": False,
                "reason": "no relevant products found"}

    links: list[dict] = []
    for q in queries:
        url = build_affiliate_url(q)
        if not url:
            continue
        meta = await fetch_product_metadata(q)
        link = {"query": q, "url": url}
        if meta:
            link["product"] = meta
        links.append(link)

    if not links:
        return {"description": description, "links": [], "added": False,
                "reason": "no affiliate URLs built"}

    # Build the section to append.
    section_lines = ["", "--- 📖 Resources mentioned ---"]
    for link in links:
        section_lines.append(f"• {link['query']}: {link['url']}")
    section_lines.append("(As an Amazon Associate I earn from qualifying purchases.)")
    enriched = description.rstrip() + "\n" + "\n".join(section_lines) + "\n"

    log.info("enriched description with %d affiliate links", len(links))
    return {
        "description": enriched,
        "links": links,
        "added": True,
        "reason": f"added {len(links)} affiliate links",
    }
