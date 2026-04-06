"""네이버 스마트플레이스 업체 크롤러 - CLI 진입점"""

import asyncio
import logging
import random
import sys
from datetime import datetime

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

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def scrape_place(
    category: str,
    region: str,
    max_results: int,
    output: str,
    headed: bool,
    delay_min: float,
    delay_max: float,
    deep_search: bool = False,
) -> None:
    """네이버 플레이스 기반 크롤링"""
    businesses: list[Business] = []

    async with create_browser(headed=headed) as (browser, context, page):
        try:
            search_frame = await navigate_to_search(page, region, category)
            entries = await collect_all_entries(page, search_frame, max_results)

            if not entries:
                logger.warning("검색 결과가 없습니다")
                export_to_excel([], output)
                return

            mode_str = " [심층탐색 ON]" if deep_search else ""
            logger.info(f"총 {len(entries)}개 업체 발견, 상세 정보 추출 시작...{mode_str}")

            search_frame = await get_search_frame(page)

            for idx, entry in enumerate(entries):
                logger.info(
                    f"[{idx + 1}/{len(entries)}] '{entry['name']}' 처리 중..."
                )
                entry["_click_index"] = idx

                biz = await click_and_extract(
                    page, search_frame, entry, category,
                    context=context,
                )
                if biz:
                    businesses.append(biz)

                delay = random.uniform(delay_min, delay_max)
                await asyncio.sleep(delay)

                if (idx + 1) % LONG_PAUSE_INTERVAL == 0 and idx + 1 < len(entries):
                    pause = random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX)
                    logger.info(f"차단 방지를 위해 {pause:.0f}초 대기 중...")
                    await asyncio.sleep(pause)

                try:
                    search_frame = await get_search_frame(page)
                except Exception:
                    logger.warning("검색 프레임 재확인 실패, 페이지 새로고침 시도")
                    await navigate_to_search(page, region, category)
                    search_frame = await get_search_frame(page)

        except KeyboardInterrupt:
            logger.info("사용자에 의해 중단됨")
        except Exception as e:
            logger.error(f"크롤링 중 오류 발생: {e}")
        finally:
            _save_and_report(businesses, output)


async def scrape_blog(
    category: str,
    region: str,
    max_results: int,
    output: str,
    headed: bool,
    delay_min: float,
    delay_max: float,
) -> None:
    """네이버 블로그 검색 기반 크롤링"""
    from scraper.blog_search import scrape_blog_search

    businesses: list[Business] = []

    async with create_browser(headed=headed) as (browser, context, page):
        try:
            businesses = await scrape_blog_search(
                context, page, region, category,
                max_posts=max_results,
                delay_min=delay_min,
                delay_max=delay_max,
            )
        except KeyboardInterrupt:
            logger.info("사용자에 의해 중단됨")
        except Exception as e:
            logger.error(f"크롤링 중 오류 발생: {e}")
        finally:
            _save_and_report(businesses, output)


def _save_and_report(businesses: list[Business], output: str) -> None:
    """결과 저장 및 통계 출력"""
    if businesses:
        export_to_excel(businesses, output)
        logger.info(f"결과 저장 완료: {output} (총 {len(businesses)}건)")

        with_phone = sum(1 for b in businesses if b.phone)
        with_personal = sum(1 for b in businesses if b.personal_phone)
        with_email = sum(1 for b in businesses if b.email)
        with_blog = sum(1 for b in businesses if b.blog_url)
        logger.info(
            f"통계 - 대표전화: {with_phone}건, "
            f"010번호: {with_personal}건, "
            f"이메일: {with_email}건, "
            f"블로그: {with_blog}건"
        )
    else:
        logger.warning("수집된 데이터가 없습니다")
        export_to_excel([], output)


@click.command()
@click.option(
    "--category", "-c",
    required=True,
    help="업종 카테고리 (예: 카페, 음식점, 미용실)",
)
@click.option(
    "--region", "-r",
    required=True,
    help="지역 (예: 서울 강남, 부산 해운대)",
)
@click.option(
    "--max-results", "-n",
    default=50,
    show_default=True,
    help="최대 수집 수",
)
@click.option(
    "--output", "-o",
    default=None,
    help="출력 파일명 (기본: 자동 생성)",
)
@click.option(
    "--headed",
    is_flag=True,
    default=False,
    help="브라우저 화면 표시 (디버깅용)",
)
@click.option(
    "--mode", "-m",
    type=click.Choice(["place", "blog"], case_sensitive=False),
    default="place",
    show_default=True,
    help="수집 모드: place=네이버플레이스, blog=블로그검색(최신순)",
)
@click.option(
    "--deep-search", "-d",
    is_flag=True,
    default=False,
    help="[place 모드] 블로그/홈페이지에서 010번호, 이메일 추가 탐색",
)
@click.option(
    "--delay-min",
    default=DEFAULT_DELAY_MIN,
    show_default=True,
    help="최소 딜레이 (초)",
)
@click.option(
    "--delay-max",
    default=DEFAULT_DELAY_MAX,
    show_default=True,
    help="최대 딜레이 (초)",
)
def main(
    category: str,
    region: str,
    max_results: int,
    output: str | None,
    headed: bool,
    mode: str,
    deep_search: bool,
    delay_min: float,
    delay_max: float,
) -> None:
    """네이버 업체 정보 크롤러

    네이버 플레이스 또는 블로그 검색에서 업체 정보를 수집합니다.

    \b
    [place 모드] 네이버 플레이스 목록에서 수집:
      python main.py -c "카페" -r "서울 강남" -n 100
      python main.py -c "미용실" -r "부산 해운대" -d  (심층탐색)

    \b
    [blog 모드] 블로그 검색 최신순에서 수집:
      python main.py -m blog -c "미용실" -r "안양" -n 50
    """
    if max_results > MAX_RESULTS:
        logger.warning(f"최대 수집 수를 {MAX_RESULTS}건으로 제한합니다")
        max_results = MAX_RESULTS

    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_region = region.replace(" ", "_")
        safe_category = category.replace(" ", "_")
        output = f"naver_{mode}_{safe_region}_{safe_category}_{timestamp}.xlsx"

    mode_label = {"place": "플레이스", "blog": "블로그검색"}[mode]
    click.echo(f"크롤링 시작: {region} {category} (모드: {mode_label}, 최대 {max_results}건)")
    click.echo(f"출력 파일: {output}")
    click.echo("-" * 50)

    if mode == "place":
        asyncio.run(
            scrape_place(
                category, region, max_results, output,
                headed, delay_min, delay_max, deep_search,
            )
        )
    elif mode == "blog":
        asyncio.run(
            scrape_blog(
                category, region, max_results, output,
                headed, delay_min, delay_max,
            )
        )


if __name__ == "__main__":
    main()
