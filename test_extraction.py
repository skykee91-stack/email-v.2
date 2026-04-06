"""추출률 테스트 스크립트
실제로 네이버 플레이스에서 업체를 수집하고
상호명/이메일/전화번호 추출률을 측정한다.
"""

import asyncio
import logging
import json
from datetime import datetime

from scraper.browser import create_browser
from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
from scraper.detail import click_and_extract
from config import DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX
import random

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def test_extraction(region: str, category: str, max_results: int = 30):
    """추출률 테스트"""
    results = []

    async with create_browser(headed=False) as (browser, context, page):
        logger.info(f"=== 테스트 시작: {region} {category} (최대 {max_results}개) ===")

        search_frame = await navigate_to_search(page, region, category)
        entries = await collect_all_entries(page, search_frame, max_results)

        if not entries:
            logger.error("검색 결과 없음!")
            return results

        total = len(entries)
        logger.info(f"총 {total}개 업체 발견")
        search_frame = await get_search_frame(page)

        for idx, entry in enumerate(entries):
            logger.info(f"\n[{idx+1}/{total}] '{entry['name']}' 처리 중...")

            biz = await click_and_extract(
                page, search_frame, entry, category,
                context=context,
                search_region=region,
            )

            results.append({
                "name": biz.name,
                "phone": biz.phone,
                "email": biz.email,
                "address": biz.address,
                "personal_phone": biz.personal_phone,
                "blog_url": biz.blog_url,
                "homepage_url": biz.homepage_url,
                "naver_id": biz.naver_id,
                "place_id": biz.place_id,
            })

            await asyncio.sleep(random.uniform(DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX))

            try:
                search_frame = await get_search_frame(page)
            except Exception:
                search_frame = await navigate_to_search(page, region, category)
                search_frame = await get_search_frame(page)

    return results


def print_report(results, region, category):
    """추출률 보고서 출력"""
    total = len(results)
    if total == 0:
        print("결과 없음!")
        return

    has_name = sum(1 for r in results if r["name"])
    has_phone = sum(1 for r in results if r["phone"])
    has_email = sum(1 for r in results if r["email"])
    has_address = sum(1 for r in results if r["address"])
    has_personal = sum(1 for r in results if r["personal_phone"])
    has_blog = sum(1 for r in results if r["blog_url"])
    has_homepage = sum(1 for r in results if r["homepage_url"])
    has_naver_id = sum(1 for r in results if r.get("naver_id"))
    has_place_id = sum(1 for r in results if r.get("place_id"))

    print("\n" + "=" * 60)
    print(f"  추출률 보고서: {region} {category}")
    print(f"  테스트 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"  총 업체 수: {total}개")
    print(f"  {'항목':<15} {'추출':<8} {'비율':<10} {'결과'}")
    print("-" * 60)

    items = [
        ("상호명", has_name),
        ("대표전화", has_phone),
        ("이메일", has_email),
        ("주소", has_address),
        ("네이버ID", has_naver_id),
        ("PlaceID", has_place_id),
        ("010번호", has_personal),
        ("블로그", has_blog),
        ("홈페이지", has_homepage),
    ]

    for label, count in items:
        rate = (count / total) * 100
        status = "PASS" if rate >= 60 else "FAIL"
        bar = "#" * int(rate / 5) + "-" * (20 - int(rate / 5))
        print(f"  {label:<15} {count}/{total:<5} {rate:>5.1f}%  {bar}  {status}")

    # 핵심 지표 (상호명 + 이메일)
    core_rate = ((has_name + has_email) / (total * 2)) * 100
    print("-" * 60)
    print(f"  핵심 추출률 (상호명+이메일): {core_rate:.1f}%")
    print(f"  목표: 60% 이상 → {'달성!' if core_rate >= 60 else '미달'}")
    print("=" * 60)

    # 각 업체별 상세
    print("\n--- 업체별 상세 ---")
    for i, r in enumerate(results, 1):
        email_str = r["email"] or "X"
        nid_str = r.get("naver_id") or "X"
        pid_str = r.get("place_id") or "X"
        print(f"  {i:>3}. {r['name'][:20]:<20} NaverID:{nid_str:<18} Email:{email_str:<25} PlaceID:{pid_str}")

    # JSON 저장
    filename = f"test_result_{region.replace(' ','_')}_{category}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump({
            "region": region,
            "category": category,
            "total": total,
            "rates": {
                "name": f"{(has_name/total)*100:.1f}%",
                "phone": f"{(has_phone/total)*100:.1f}%",
                "email": f"{(has_email/total)*100:.1f}%",
                "address": f"{(has_address/total)*100:.1f}%",
                "naver_id": f"{(has_naver_id/total)*100:.1f}%",
                "place_id": f"{(has_place_id/total)*100:.1f}%",
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {filename}")


if __name__ == "__main__":
    import sys

    # 업종별 테스트 (각 15개씩, 이메일 보유 가능성이 다른 업종들)
    tests = [
        ("서울 강남구", "학원", 15),
        ("서울 강남구", "병원", 15),
    ]

    # 명령줄 인자가 있으면 해당 업종만
    if len(sys.argv) >= 3:
        tests = [(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 15)]

    all_results = []
    for region, category, count in tests:
        results = asyncio.run(test_extraction(region, category, count))
        print_report(results, region, category)
        all_results.extend(results)

    # 전체 종합 보고
    if len(tests) > 1:
        print_report(all_results, "종합", "전체")
