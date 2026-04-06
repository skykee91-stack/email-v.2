"""
셀포 스크래퍼 API 서버
- 웹앱(Vercel)에서 원격으로 스크래퍼를 실행할 수 있게 해주는 서버
- 이 파일을 로컬 PC나 VPS에서 실행하면 됨

실행 방법:
  pip install fastapi uvicorn
  python api_server.py

그러면 http://localhost:8000 에서 API가 시작됨
웹앱 .env에 SCRAPER_API_URL=http://localhost:8000 추가
"""

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json
import random
import sys
import os
import logging
from datetime import datetime

# 스크래퍼 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING)

app = FastAPI(title="셀포 스크래퍼 API")

# CORS 허용 (웹앱에서 호출 가능하게)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 현재 작업 상태
current_job = {
    "status": "idle",  # idle / running / done / failed
    "found": 0,
    "target": 0,
    "category": "",
    "region": "",
    "results": [],
    "error": None,
    "startedAt": None,
    "finishedAt": None,
}


class ScrapeRequest(BaseModel):
    category: str
    region: str = ""
    target: int = 100


@app.get("/")
def health():
    return {"status": "ok", "service": "sellpo-scraper-api"}


@app.get("/status")
def get_status():
    return {
        "status": current_job["status"],
        "found": current_job["found"],
        "target": current_job["target"],
        "category": current_job["category"],
        "region": current_job["region"],
        "resultCount": len(current_job["results"]),
        "error": current_job["error"],
        "startedAt": current_job["startedAt"],
        "finishedAt": current_job["finishedAt"],
    }


@app.get("/results")
def get_results():
    """수집 완료된 결과 가져가기"""
    return {
        "businesses": current_job["results"],
        "total": len(current_job["results"]),
    }


@app.post("/scrape")
async def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    """수집 시작 (백그라운드에서 실행)"""
    if current_job["status"] == "running":
        return {"error": "이미 수집 중입니다", "status": current_job["status"]}

    # 상태 초기화
    current_job.update({
        "status": "running",
        "found": 0,
        "target": req.target,
        "category": req.category,
        "region": req.region or "전국",
        "results": [],
        "error": None,
        "startedAt": datetime.now().isoformat(),
        "finishedAt": None,
    })

    background_tasks.add_task(run_scrape, req.category, req.region, req.target)

    return {"ok": True, "message": f"{req.category} 수집 시작 (목표: {req.target}개)"}


async def run_scrape(category: str, region: str, target: int):
    """실제 스크래핑 실행"""
    try:
        from scraper.browser import create_browser
        from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
        from scraper.detail import click_and_extract
        from config import DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, LONG_PAUSE_INTERVAL, LONG_PAUSE_MIN, LONG_PAUSE_MAX

        results = []
        seen = set()

        if region:
            regions = [region]
        else:
            regions = [
                "서울 강남구", "서울 서초구", "서울 송파구", "서울 마포구",
                "서울 영등포구", "서울 강동구", "서울 관악구", "서울 강서구",
                "서울 성동구", "서울 종로구",
            ]

        per_region = max(30, (target * 3) // len(regions) + 10)

        async with create_browser(headed=False) as (browser, context, page):
            for ri, r in enumerate(regions):
                if len(results) >= target:
                    break
                try:
                    sf = await navigate_to_search(page, r, category)
                    entries = await collect_all_entries(page, sf, per_region)
                    if not entries:
                        continue
                    sf = await get_search_frame(page)

                    for idx, entry in enumerate(entries):
                        if len(results) >= target:
                            break
                        if entry["name"] in seen:
                            continue

                        biz = await click_and_extract(
                            page, sf, entry, category,
                            context=context, search_region=r
                        )
                        if biz:
                            seen.add(biz.name)
                            if biz.email:
                                item = {
                                    "name": biz.name,
                                    "phone": biz.phone,
                                    "email": biz.email,
                                    "address": biz.address,
                                    "category": category,
                                    "region": r,
                                    "naverId": biz.naver_id,
                                    "blogUrl": biz.blog_url,
                                    "homepageUrl": biz.homepage_url,
                                    "placeId": biz.place_id,
                                }
                                results.append(item)
                                current_job["found"] = len(results)
                                current_job["results"] = results

                        await asyncio.sleep(random.uniform(DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX))
                        if (idx + 1) % LONG_PAUSE_INTERVAL == 0:
                            await asyncio.sleep(random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX))

                        try:
                            sf = await get_search_frame(page)
                        except:
                            sf = await navigate_to_search(page, r, category)
                            sf = await get_search_frame(page)
                except Exception as e:
                    logging.warning(f"지역 {r} 수집 오류: {e}")

        current_job["status"] = "done"
        current_job["finishedAt"] = datetime.now().isoformat()

    except Exception as e:
        current_job["status"] = "failed"
        current_job["error"] = str(e)
        current_job["finishedAt"] = datetime.now().isoformat()


if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("셀포 스크래퍼 API 서버 시작")
    print("http://localhost:8000 에서 실행 중")
    print("웹앱 .env에 SCRAPER_API_URL=http://localhost:8000 추가하세요")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
