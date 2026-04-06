"""스크래핑 → DB 업로드 통합 스크립트

사용법:
    python scrape_and_push.py -c "미용실" -r "서울 강남" -n 100
    python scrape_and_push.py -c "치과" -r "부산 해운대" -n 50

스크래핑 완료 후 이메일 있는 업체를 자동으로 DB에 업로드
"""

import asyncio
import logging
import random
import sys
import os
from datetime import datetime

# 경로 설정
EXE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(EXE_DIR)

import click

from config import (
    DEFAULT_DELAY_MIN,
    DEFAULT_DELAY_MAX,
    LONG_PAUSE_INTERVAL,
    LONG_PAUSE_MIN,
    LONG_PAUSE_MAX,
    MAX_RESULTS,
)
from models.business import Business
from scraper.browser import create_browser
from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
from scraper.detail import click_and_extract
from export.excel import export_to_excel
from push_to_db import upload_via_web_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def scrape_and_push(
    category: str,
    region: str,
    max_results: int,
    headed: bool,
    delay_min: float,
    delay_max: float,
    skip_upload: bool = False,
) -> dict:
    """스크래핑 후 DB 업로드까지 한번에 처리"""
    businesses: list[Business] = []

    async with create_browser(headed=headed) as (browser, context, page):
        try:
            search_frame = await navigate_to_search(page, region, category)
            entries = await collect_all_entries(page, search_frame, max_results)

            if not entries:
                logger.warning("검색 결과가 없습니다")
                return {"total": 0, "with_email": 0, "uploaded": 0}

            logger.info(f"총 {len(entries)}개 업체 발견, 상세 정보 추출 시작 (강화된 이메일 탐색)")

            search_frame = await get_search_frame(page)

            for idx, entry in enumerate(entries):
                logger.info(f"[{idx + 1}/{len(entries)}] '{entry['name']}' 처리 중...")

                biz = await click_and_extract(
                    page, search_frame, entry, category,
                    context=context,  # context 전달 → 강화된 이메일 탐색 활성화
                )
                if biz:
                    businesses.append(biz)

                delay = random.uniform(delay_min, delay_max)
                await asyncio.sleep(delay)

                if (idx + 1) % LONG_PAUSE_INTERVAL == 0 and idx + 1 < len(entries):
                    pause = random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX)
                    logger.info(f"차단 방지 {pause:.0f}초 대기...")
                    await asyncio.sleep(pause)

                try:
                    search_frame = await get_search_frame(page)
                except Exception:
                    logger.warning("검색 프레임 재확인 실패, 페이지 새로고침")
                    await navigate_to_search(page, region, category)
                    search_frame = await get_search_frame(page)

        except KeyboardInterrupt:
            logger.info("사용자에 의해 중단됨")
        except Exception as e:
            logger.error(f"크롤링 중 오류: {e}")

    # 결과 통계
    total = len(businesses)
    with_phone = sum(1 for b in businesses if b.phone)
    with_email = sum(1 for b in businesses if b.email)
    with_personal = sum(1 for b in businesses if b.personal_phone)

    logger.info(f"\n{'='*50}")
    logger.info(f"스크래핑 완료!")
    logger.info(f"  총 업체: {total}개")
    logger.info(f"  대표전화: {with_phone}개 ({with_phone/total*100:.1f}%)" if total > 0 else "")
    logger.info(f"  이메일: {with_email}개 ({with_email/total*100:.1f}%)" if total > 0 else "")
    logger.info(f"  010번호: {with_personal}개 ({with_personal/total*100:.1f}%)" if total > 0 else "")

    # Excel 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_region = region.replace(" ", "_")
    safe_category = category.replace(" ", "_")
    output = f"result_{safe_region}_{safe_category}_{timestamp}.xlsx"
    export_to_excel(businesses, output)
    logger.info(f"Excel 저장: {output}")

    # DB 업로드
    uploaded = 0
    if not skip_upload and with_email > 0:
        logger.info(f"\nDB 업로드 시작 (이메일 있는 {with_email}개)...")

        upload_data = []
        for b in businesses:
            if not b.email:
                continue
            upload_data.append({
                "name": b.name,
                "phone": b.phone,
                "personalPhone": b.personal_phone,
                "email": b.email,
                "naverId": b.naver_id,
                "address": b.address,
                "category": b.category or category,
                "region": region,
                "blogUrl": b.blog_url,
                "homepageUrl": b.homepage_url,
                "placeId": b.place_id,
            })

        result = upload_via_web_api(upload_data)
        uploaded = result["added"]
        logger.info(f"DB 업로드 완료: 추가 {result['added']}개, 건너뜀 {result['skipped']}개")
    elif with_email == 0:
        logger.warning("이메일 있는 업체가 없어서 DB 업로드 건너뜀")

    return {"total": total, "with_email": with_email, "uploaded": uploaded}


@click.command()
@click.option("--category", "-c", required=True, help="업종 (예: 미용실, 치과, 카페)")
@click.option("--region", "-r", required=True, help="지역 (예: 서울 강남, 부산 해운대)")
@click.option("--max-results", "-n", default=100, help="최대 수집 수")
@click.option("--headed", is_flag=True, default=False, help="브라우저 화면 표시")
@click.option("--skip-upload", is_flag=True, default=False, help="DB 업로드 건너뛰기")
@click.option("--delay-min", default=DEFAULT_DELAY_MIN, help="최소 딜레이 (초)")
@click.option("--delay-max", default=DEFAULT_DELAY_MAX, help="최대 딜레이 (초)")
def main(category, region, max_results, headed, skip_upload, delay_min, delay_max):
    """네이버 플레이스 스크래핑 → DB 업로드 통합 스크립트"""
    if max_results > MAX_RESULTS:
        max_results = MAX_RESULTS

    click.echo(f"🔍 {region} {category} 스크래핑 시작 (최대 {max_results}건)")
    click.echo(f"   강화된 이메일 탐색 활성화")
    click.echo(f"   DB 업로드: {'OFF' if skip_upload else 'ON'}")
    click.echo("-" * 50)

    result = asyncio.run(
        scrape_and_push(
            category, region, max_results,
            headed, delay_min, delay_max, skip_upload,
        )
    )

    click.echo(f"\n{'='*50}")
    click.echo(f"최종 결과:")
    click.echo(f"  스크래핑: {result['total']}개")
    click.echo(f"  이메일 확보: {result['with_email']}개")
    click.echo(f"  DB 업로드: {result['uploaded']}개")


if __name__ == "__main__":
    main()
