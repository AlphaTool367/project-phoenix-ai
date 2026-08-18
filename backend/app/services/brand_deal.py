"""Brand deal CRM — track sponsorship deals, calculate rates, generate outreach emails.

Helps the user monetize their channel through brand deals:
  - BrandDeal table: tracks potential + active sponsors
  - Rate calculator: suggests a fair sponsorship rate based on metrics
  - Outreach email generator: LLM writes a pitch email to a brand
  - Sponsor disclosure helper: adds #ad to video descriptions
"""
from __future__ import annotations

from datetime import datetime

from ..core.logging import get_logger
from ..core.utils import clamp
from ..database import session_scope
from ..models import Channel, Video
from . import llm
from .revenue_tracker import NICHE_RPM_USD

log = get_logger("brand_deal")


def calculate_sponsorship_rate(channel_id: int) -> dict:
    """Calculate a fair sponsorship rate for the channel.

    Industry standard: $20-30 per 1,000 views for a 60s integration.
    Formula: (avg_views / 1000) * $20-30 * (niche_multiplier)

    Returns:
      {
        "rate_low": float,   # minimum acceptable rate
        "rate_high": float,  # maximum to ask for
        "rate_suggested": float,  # sweet spot
        "avg_views": int,
        "niche": str,
        "niche_multiplier": float,
        "formula": str,
      }
    """
    from ..models import AnalyticsSnapshot
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        if not ch:
            return {"available": False, "reason": "channel not found"}
        niche = ch.niche
        # Get avg views from latest snapshots.
        snaps = (db.query(AnalyticsSnapshot)
                 .filter_by(channel_id=channel_id)
                 .order_by(AnalyticsSnapshot.captured_at.desc())
                 .limit(50).all())
        if snaps:
            avg_views = sum(s.views for s in snaps) / len(snaps)
        else:
            avg_views = 0
        subs = ch.yt_subscriber_count or 0
    # Niche multiplier — finance/tech pay more than entertainment/gaming.
    niche_mult = NICHE_RPM_USD.get(niche, 5.0) / 5.0  # normalize to 1.0
    base_cpm = 20.0  # $20 per 1K views baseline
    rate_low = (avg_views / 1000.0) * base_cpm * niche_mult
    rate_high = rate_low * 1.5
    rate_suggested = (rate_low + rate_high) / 2
    return {
        "available": True,
        "rate_low": round(rate_low, 2),
        "rate_high": round(rate_high, 2),
        "rate_suggested": round(rate_suggested, 2),
        "avg_views": int(avg_views),
        "subscribers": subs,
        "niche": niche,
        "niche_multiplier": round(niche_mult, 2),
        "formula": f"({int(avg_views)} views / 1000) × ${base_cpm} × {niche_mult:.1f} niche mult",
    }


async def generate_outreach_email(brand_name: str, product: str,
                                   channel_id: int) -> str:
    """Generate a sponsorship pitch email to a brand."""
    with session_scope() as db:
        ch = db.get(Channel, channel_id)
        channel_name = ch.name if ch else "my channel"
        niche = ch.niche if ch else "technology"
    rate = calculate_sponsorship_rate(channel_id)
    suggested = rate.get("rate_suggested", 0)
    avg_views = rate.get("avg_views", 0)
    subs = rate.get("subscribers", 0)
    prompt = [
        {"role": "system", "content": (
            "You are a sponsorship outreach expert. Write a professional but "
            "warm pitch email to a brand for a YouTube sponsorship. Include: "
            "who you are, why their product fits your audience, your metrics, "
            "your proposed rate, and a clear next step. Keep it under 300 words. "
            "Respond ONLY with the email text."
        )},
        {"role": "user", "content": (
            f"Brand: {brand_name}\nProduct: {product}\n"
            f"Channel: {channel_name}\nNiche: {niche}\n"
            f"Subscribers: {subs:,}\nAvg views: {avg_views:,}\n"
            f"Suggested rate: ${suggested}"
        )},
    ]
    text = await llm.chat(prompt, temperature=0.7)
    return text or f"Subject: Partnership opportunity with {channel_name}\n\nHi {brand_name} team..."


def list_brand_deals(channel_id: int) -> list[dict]:
    """List all brand deals for a channel."""
    from ..models import BrandDeal
    with session_scope() as db:
        rows = db.query(BrandDeal).filter_by(channel_id=channel_id).all()
        return [{"id": r.id, "brand_name": r.brand_name, "product": r.product,
                 "status": r.status, "rate_usd": r.rate_usd,
                 "contact_email": r.contact_email,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "notes": r.notes}
                for r in rows]


def create_brand_deal(channel_id: int, brand_name: str, product: str,
                      contact_email: str = "", rate_usd: float = 0,
                      notes: str = "") -> dict:
    """Create a new brand deal record."""
    from ..models import BrandDeal
    with session_scope() as db:
        bd = BrandDeal(
            channel_id=channel_id,
            brand_name=brand_name,
            product=product,
            contact_email=contact_email,
            rate_usd=rate_usd,
            status="pitched",
            notes=notes,
        )
        db.add(bd)
        db.flush()
        return {"created": True, "id": bd.id, "brand_name": brand_name}


def update_brand_deal_status(deal_id: int, status: str) -> dict:
    """Update a brand deal's status (pitched → negotiating → confirmed → completed → rejected)."""
    from ..models import BrandDeal
    valid = ["pitched", "negotiating", "confirmed", "completed", "rejected"]
    if status not in valid:
        return {"updated": False, "reason": f"invalid status (must be one of {valid})"}
    with session_scope() as db:
        bd = db.get(BrandDeal, deal_id)
        if not bd:
            return {"updated": False, "reason": "not found"}
        bd.status = status
        return {"updated": True, "id": deal_id, "status": status}
