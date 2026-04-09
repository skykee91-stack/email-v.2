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
    '울산': ['울산 남구','울산 중구','울산 북구','울산 동구','울산 울주군'],
    '세종': ['세종시'],
    '제주': ['제주 제주시','제주 서귀포시'],
    '고양': ['고양 일산동구','고양 일산서구','고양 덕양구'],
    '용인': ['용인 수지구','용인 기흥구','용인 처인구'],
    '창원': ['창원 성산구','창원 의창구','창원 마산합포구','창원 마산회원구','창원 진해구'],
    '천안': ['천안 서북구','천안 동남구'],
    '청주': ['청주 흥덕구','청주 서원구','청주 청원구','청주 상당구'],
    '전주': ['전주 덕진구','전주 완산구'],
    '포항': ['포항 남구','포항 북구'],
}

# 전국 모드: 모든 도시를 합침
ALL_REGIONS = []
for city_districts in CITY_TO_DISTRICTS.values():
    ALL_REGIONS.extend(city_districts)


# ─── 수집 히스토리 (이전 수집 업체 중복 방지) ───
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collected_history.json')


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f).get('collected_ids', []))
        except Exception:
            return set()
    return set()


def save_history(collected_ids):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump({'collected_ids': list(collected_ids)}, f, ensure_ascii=False)
    except Exception as e:
        logging.error(f'히스토리 저장 실패: {e}')


def _save_intermediate(results, result_path):
    """중간 저장 — 수집 중 프로세스가 죽어도 여기까지 모은 데이터 보존"""
    try:
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump({'businesses': results}, f, ensure_ascii=False)
    except Exception:
        pass


async def scrape(category: str, regions: list, target: int, custom_keywords: list = None):
    from scraper.browser import create_browser
    from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
    from scraper.detail import click_and_extract
    from config import DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, LONG_PAUSE_INTERVAL, LONG_PAUSE_MIN, LONG_PAUSE_MAX
    from data import KEYWORD_GROUPS

    results = []
    history_ids = load_history()
    seen_ids = set(history_ids)  # 이전 수집 히스토리 포함
    result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_scrape_result.json')

    # 관련 키워드: 웹에서 보낸 키워드 우선, 없으면 자동 로드
    if custom_keywords and len(custom_keywords) > 0:
        search_keywords = custom_keywords
    else:
        search_keywords = KEYWORD_GROUPS.get(category, [category])
    per_region = max(30, (target * 2) // (len(regions) * len(search_keywords)) + 10)

    logging.warning(f"검색 키워드: {search_keywords}, 기존 히스토리: {len(history_ids)}개")

    # 조기 종료: 연속 15개 지역에서 새 업체 0개면 더 이상 찾을 게 없다고 판단
    empty_streak = 0
    MAX_EMPTY_STREAK = 15

    async with create_browser(headed=False) as (browser, context, page):
        for keyword in search_keywords:
            if len(results) >= target:
                break
            if empty_streak >= MAX_EMPTY_STREAK:
                logging.warning(f"연속 {MAX_EMPTY_STREAK}개 지역에서 새 업체 0개 → 조기 종료")
                break

            for ri, region in enumerate(regions):
                if len(results) >= target:
                    break
                if empty_streak >= MAX_EMPTY_STREAK:
                    break
                region_found_before = len(results)
                try:
                    sf = await navigate_to_search(page, region, keyword)
                    entries = await collect_all_entries(page, sf, per_region)
                    if not entries:
                        continue
                    sf = await get_search_frame(page)
                    for idx, entry in enumerate(entries):
                        if len(results) >= target:
                            break
                        biz = await click_and_extract(
                            page, sf, entry, category,
                            context=context, search_region=region
                        )
                        if biz:
                            # place_id 기준 중복 체크 (없으면 이름+주소)
                            dedup_key = biz.place_id or f"{biz.name}|{biz.address or ''}"
                            if dedup_key not in seen_ids:
                                seen_ids.add(dedup_key)
                                history_ids.add(dedup_key)
                                results.append({
                                    'name': biz.name,
                                    'phone': biz.phone,
                                    'email': biz.email or '',
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
                                    'email': biz.email or '없음'
                                }, ensure_ascii=False), flush=True)

                                # 10건마다 중간 저장 (중단돼도 데이터 보존)
                                if len(results) % 10 == 0:
                                    _save_intermediate(results, result_path)
                                    save_history(history_ids)
                        await asyncio.sleep(random.uniform(DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX))
                        if (idx + 1) % LONG_PAUSE_INTERVAL == 0:
                            await asyncio.sleep(random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX))
                        try:
                            sf = await get_search_frame(page)
                        except:
                            sf = await navigate_to_search(page, region, keyword)
                            sf = await get_search_frame(page)
                except Exception as e:
                    logging.warning(f"지역 {region} '{keyword}' 수집 오류: {e}")

                # 이 지역에서 새 업체를 하나도 못 찾았으면 empty_streak 증가
                if len(results) == region_found_before:
                    empty_streak += 1
                else:
                    empty_streak = 0

    # 최종 저장
    save_history(history_ids)

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
    custom_keywords = None
    if env_hex:
        config = json.loads(bytes.fromhex(env_hex).decode('utf-8'))
        category = config['category']
        target = config.get('target', 100)
        region = config.get('region', '')
        custom_keywords = config.get('keywords', None)
    elif args.config and os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)
        category = config['category']
        target = config.get('target', 100)
        region = config.get('region', '')
        custom_keywords = config.get('keywords', None)
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
    elif region == '전국':
        regions = ALL_REGIONS
    elif region in CITY_TO_DISTRICTS:
        regions = CITY_TO_DISTRICTS[region]
    else:
        regions = [region]

    # 빈 리스트면 None 처리 (자동 키워드 로드되게)
    if custom_keywords and len(custom_keywords) == 0:
        custom_keywords = None
    asyncio.run(scrape(category, regions, target, custom_keywords))


if __name__ == '__main__':
    main()
