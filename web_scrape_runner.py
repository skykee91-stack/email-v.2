# -*- coding: utf-8 -*-
"""
웹앱에서 호출하는 스크래퍼 실행기
사용법: python web_scrape_runner.py --category 치과 --region "서울 강남구" --target 100
       python web_scrape_runner.py --category 입주청소 --region 서울 --target 100
"""
import asyncio
import json
import random
import sys
import os
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.WARNING)

# 시/도 → 구 자동 분배
CITY_TO_DISTRICTS = {
    '서울': ['서울 강남구','서울 서초구','서울 송파구','서울 마포구','서울 영등포구','서울 강동구','서울 관악구','서울 강서구','서울 성동구','서울 종로구','서울 중구','서울 용산구','서울 광진구','서울 동대문구','서울 중랑구','서울 성북구','서울 강북구','서울 도봉구','서울 노원구','서울 은평구','서울 서대문구','서울 구로구','서울 금천구','서울 동작구','서울 양천구'],
    '부산': ['부산 해운대구','부산 수영구','부산 남구','부산 동래구','부산 부산진구','부산 사하구','부산 북구','부산 사상구','부산 연제구','부산 금정구'],
    '인천': ['인천 남동구','인천 부평구','인천 서구','인천 연수구','인천 미추홀구','인천 계양구','인천 중구','인천 동구'],
    '대구': ['대구 수성구','대구 달서구','대구 북구','대구 중구','대구 동구','대구 서구','대구 남구'],
    '대전': ['대전 유성구','대전 서구','대전 중구','대전 동구','대전 대덕구'],
    '광주': ['광주 북구','광주 서구','광주 남구','광주 광산구','광주 동구'],
    '수원': ['수원 영통구','수원 권선구','수원 장안구','수원 팔달구'],
    '성남': ['성남 분당구','성남 수정구','성남 중원구'],
}


async def scrape(category: str, regions: list, target: int):
    from scraper.browser import create_browser
    from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
    from scraper.detail import click_and_extract
    from config import DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, LONG_PAUSE_INTERVAL, LONG_PAUSE_MIN, LONG_PAUSE_MAX

    results = []
    seen = set()
    per_region = max(30, (target * 3) // len(regions) + 10)

    async with create_browser(headed=False) as (browser, context, page):
        for ri, region in enumerate(regions):
            if len(results) >= target:
                break
            try:
                sf = await navigate_to_search(page, region, category)
                entries = await collect_all_entries(page, sf, per_region)
                if not entries:
                    continue
                sf = await get_search_frame(page)
                for idx, entry in enumerate(entries):
                    if len(results) >= target:
                        break
                    if entry['name'] in seen:
                        continue
                    biz = await click_and_extract(
                        page, sf, entry, category,
                        context=context, search_region=region
                    )
                    if biz:
                        seen.add(biz.name)
                        if biz.email:
                            results.append({
                                'name': biz.name,
                                'phone': biz.phone,
                                'email': biz.email,
                                'address': biz.address,
                                'category': category,
                                'region': region,
                                'naverId': biz.naver_id,
                                'blogUrl': biz.blog_url,
                                'homepageUrl': biz.homepage_url,
                                'placeId': biz.place_id,
                            })
                            print(json.dumps({
                                'found': len(results),
                                'name': biz.name,
                                'email': biz.email
                            }, ensure_ascii=False), flush=True)
                    await asyncio.sleep(random.uniform(DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX))
                    if (idx + 1) % LONG_PAUSE_INTERVAL == 0:
                        await asyncio.sleep(random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX))
                    try:
                        sf = await get_search_frame(page)
                    except:
                        sf = await navigate_to_search(page, region, category)
                        sf = await get_search_frame(page)
            except Exception as e:
                logging.warning(f"지역 {region} 수집 오류: {e}")

    result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_scrape_result.json')
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump({'businesses': results}, f, ensure_ascii=False)
    print(json.dumps({'done': True, 'total': len(results)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--category', default='', help='검색 카테고리/검색어')
    parser.add_argument('--region', default='', help='지역 (서울, 부산, 서울 강남구 등)')
    parser.add_argument('--target', type=int, default=100, help='목표 수집 수')
    parser.add_argument('--config', default='', help='JSON 설정 파일 경로')
    args = parser.parse_args()

    # 우선순위: hex 환경변수 > 환경변수 > config 파일 > 커맨드라인 인자
    env_hex = os.environ.get('SCRAPE_CONFIG_HEX', '')
    env_config = os.environ.get('SCRAPE_CONFIG', '')
    if env_hex:
        config = json.loads(bytes.fromhex(env_hex).decode('utf-8'))
        category = config['category']
        target = config.get('target', 100)
        region = config.get('region', '')
    elif args.config and os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)
        category = config['category']
        target = config.get('target', 100)
        region = config.get('region', '')
    else:
        category = args.category
        region = args.region
        target = args.target

    if not category:
        print(json.dumps({'done': True, 'total': 0, 'error': 'category required'}))
        return

    # 지역 자동 분배
    if not region:
        regions = CITY_TO_DISTRICTS['서울']
    elif region in CITY_TO_DISTRICTS:
        regions = CITY_TO_DISTRICTS[region]
    else:
        regions = [region]

    asyncio.run(scrape(category, regions, target))


if __name__ == '__main__':
    main()
