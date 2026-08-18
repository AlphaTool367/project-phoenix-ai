"""Routes for all v1.8 features — repurposing, content types, analytics pro,
brand deals, smart automation, multi-platform, AI assistant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import Channel, Video
from ..services import (analytics_pro, ai_assistant, brand_deal, content_types,
                        multi_platform, repurposing, smart_automation)
from .deps import get_db

router = APIRouter(prefix="/api/v18", tags=["v1.8"])


# ----------------------------------------------------- content types

@router.get("/content-types")
def list_content_types():
    return {"types": content_types.CONTENT_TYPES}


# ----------------------------------------------------- repurposing

class RepurposeRequest(BaseModel):
    video_id: int
    format: str = "all"  # blog|twitter|linkedin|reddit|medium|newsletter|podcast|all


@router.post("/repurpose")
async def repurpose(body: RepurposeRequest, db: Session = Depends(get_db)):
    v = db.get(Video, body.video_id)
    if not v:
        raise HTTPException(404, "video not found")
    script = v.script_json or {}
    title = v.title or v.topic
    video_file = v.file_path
    if body.format == "all":
        result = await repurposing.repurpose_all(script, title, video_file)
    elif body.format == "podcast":
        result = await repurposing.to_podcast(video_file) if video_file else {"error": "no file"}
    else:
        fn = {
            "blog": repurposing.to_blog_post,
            "twitter": repurposing.to_twitter_thread,
            "linkedin": repurposing.to_linkedin_article,
            "reddit": repurposing.to_reddit_post,
            "medium": repurposing.to_medium_article,
            "newsletter": repurposing.to_newsletter,
        }.get(body.format)
        if not fn:
            raise HTTPException(400, f"unknown format: {body.format}")
        result = await fn(script, title)
    return {"video_id": body.video_id, "format": body.format, "result": result}


# ----------------------------------------------------- analytics pro

@router.get("/analytics-pro/demographics/{channel_id}")
def demographics(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return analytics_pro.fetch_demographics(channel_id, days)


@router.get("/analytics-pro/traffic/{channel_id}")
def traffic_sources(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return analytics_pro.fetch_traffic_sources(channel_id, days)


@router.get("/analytics-pro/geography/{channel_id}")
def geography(channel_id: int, days: int = 30, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return analytics_pro.fetch_geography(channel_id, days)


@router.get("/analytics-pro/anomalies/{channel_id}")
def anomalies(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return {"anomalies": analytics_pro.detect_anomalies(channel_id)}


@router.post("/analytics-pro/sentiment/{video_id}")
async def comment_sentiment(video_id: int, db: Session = Depends(get_db)):
    if not db.get(Video, video_id):
        raise HTTPException(404, "video not found")
    return await analytics_pro.analyze_comment_sentiment(video_id)


# ----------------------------------------------------- smart automation

@router.post("/smart/dead-videos/{channel_id}")
def auto_private_dead(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return smart_automation.auto_private_dead_videos(channel_id)


@router.get("/smart/dead-videos/{channel_id}")
def list_dead_videos(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return {"dead_videos": smart_automation.find_dead_videos(channel_id)}


@router.post("/smart/coppa/{video_id}")
async def coppa_check(video_id: int, db: Session = Depends(get_db)):
    if not db.get(Video, video_id):
        raise HTTPException(404, "video not found")
    return await smart_automation.check_coppa(video_id)


@router.post("/smart/milestones/{channel_id}")
def check_milestones(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return smart_automation.check_milestones(channel_id)


@router.post("/smart/milestone-script/{channel_id}")
async def milestone_script(channel_id: int, milestone: int = 1000,
                            db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return await smart_automation.generate_milestone_script(channel_id, milestone)


# ----------------------------------------------------- brand deals

class BrandDealCreate(BaseModel):
    brand_name: str = Field(min_length=1, max_length=200)
    product: str = Field(default="", max_length=300)
    contact_email: str = Field(default="", max_length=200)
    rate_usd: float = Field(default=0, ge=0)
    notes: str = ""


@router.get("/brand-deals/{channel_id}")
def list_deals(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return brand_deal.list_brand_deals(channel_id)


@router.post("/brand-deals/{channel_id}")
def create_deal(channel_id: int, body: BrandDealCreate,
                db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return brand_deal.create_brand_deal(
        channel_id, body.brand_name, body.product,
        body.contact_email, body.rate_usd, body.notes)


@router.patch("/brand-deals/{deal_id}")
def update_deal(deal_id: int, status: str, db: Session = Depends(get_db)):
    return brand_deal.update_brand_deal_status(deal_id, status)


@router.get("/brand-deals/{channel_id}/rate")
def sponsorship_rate(channel_id: int, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    return brand_deal.calculate_sponsorship_rate(channel_id)


@router.post("/brand-deals/{channel_id}/outreach")
async def outreach_email(channel_id: int, brand_name: str, product: str,
                          db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise HTTPException(404, "channel not found")
    email = await brand_deal.generate_outreach_email(brand_name, product, channel_id)
    return {"email": email}


# ----------------------------------------------------- multi-platform

class PlatformSEORequest(BaseModel):
    video_id: int
    platform: str = "all"


@router.post("/multi-platform/seo")
async def platform_seo(body: PlatformSEORequest, db: Session = Depends(get_db)):
    v = db.get(Video, body.video_id)
    if not v:
        raise HTTPException(404, "video not found")
    script = v.script_json or {}
    title = v.title or v.topic
    if body.platform == "all":
        result = await multi_platform.generate_all_platforms(script, v.niche, title)
    else:
        result = await multi_platform.generate_platform_metadata(
            script, v.niche, body.platform, title)
    return {"video_id": body.video_id, "platform": body.platform, "result": result}


@router.get("/multi-platform/platforms")
def list_platforms():
    return {"platforms": list(multi_platform.PLATFORM_LIMITS.keys()),
            "limits": multi_platform.PLATFORM_LIMITS}


@router.post("/multi-platform/srt/{video_id}")
def export_srt(video_id: int, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise HTTPException(404, "video not found")
    script = v.script_json or {}
    srt = multi_platform.export_srt_subtitles(script)
    return {"video_id": video_id, "srt": srt}


# ----------------------------------------------------- AI assistant

class ChatRequest(BaseModel):
    channel_id: int
    message: str


@router.post("/assistant/chat")
async def assistant_chat(body: ChatRequest, db: Session = Depends(get_db)):
    if not db.get(Channel, body.channel_id):
        raise HTTPException(404, "channel not found")
    return await ai_assistant.chat(body.channel_id, body.message)
