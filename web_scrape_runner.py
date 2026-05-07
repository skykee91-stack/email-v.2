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

# 추가 지역 — 기존 8개 시군 외에 142개 시군 추가 (총 238개 행정구역)
# 경기/강원/충북/충남/전북/전남/경북/경남 커버 → DB에 안 모은 새 업체 발견 가능성 ↑
EXTRA_REGIONS = [
    # 경기 (수원/성남/고양/용인 4개는 이미 위에 districts 있음)
    "경기 부천", "경기 안산", "경기 안양", "경기 남양주", "경기 화성",
    "경기 평택", "경기 의정부", "경기 시흥", "경기 파주", "경기 김포",
    "경기 광명", "경기 광주", "경기 군포", "경기 하남", "경기 오산",
    "경기 이천", "경기 안성", "경기 의왕", "경기 양평", "경기 여주",
    "경기 동두천", "경기 과천", "경기 가평", "경기 연천", "경기 포천",
    "경기 양주", "경기 구리",
    # 강원
    "강원 춘천", "강원 원주", "강원 강릉", "강원 동해", "강원 태백",
    "강원 속초", "강원 삼척", "강원 홍천", "강원 횡성", "강원 영월",
    "강원 평창", "강원 정선", "강원 철원", "강원 화천", "강원 양구",
    "강원 인제", "강원 고성", "강원 양양",
    # 충북 (청주 이미 위에 있음)
    "충북 충주", "충북 제천", "충북 보은", "충북 옥천", "충북 영동",
    "충북 진천", "충북 괴산", "충북 음성", "충북 단양",
    # 충남 (천안 이미 위에 있음)
    "충남 공주", "충남 보령", "충남 아산", "충남 서산", "충남 논산",
    "충남 계룡", "충남 당진", "충남 금산", "충남 부여", "충남 서천",
    "충남 청양", "충남 홍성", "충남 예산", "충남 태안",
    # 전북 (전주 이미 위에 있음)
    "전북 군산", "전북 익산", "전북 정읍", "전북 남원", "전북 김제",
    "전북 완주", "전북 진안", "전북 무주", "전북 장수", "전북 임실",
    "전북 순창", "전북 고창", "전북 부안",
    # 전남
    "전남 목포", "전남 여수", "전남 순천", "전남 나주", "전남 광양",
    "전남 담양", "전남 곡성", "전남 구례", "전남 고흥", "전남 보성",
    "전남 화순", "전남 장흥", "전남 강진", "전남 해남", "전남 영암",
    "전남 무안", "전남 함평", "전남 영광", "전남 장성", "전남 완도",
    "전남 진도", "전남 신안",
    # 경북 (포항 이미 위에 있음)
    "경북 경주", "경북 김천", "경북 안동", "경북 구미", "경북 영주",
    "경북 영천", "경북 상주", "경북 문경", "경북 경산", "경북 군위",
    "경북 의성", "경북 청송", "경북 영양", "경북 영덕", "경북 청도",
    "경북 고령", "경북 성주", "경북 칠곡", "경북 예천", "경북 봉화",
    "경북 울진", "경북 울릉",
    # 경남 (창원 이미 위에 있음)
    "경남 진주", "경남 통영", "경남 사천", "경남 김해", "경남 밀양",
    "경남 거제", "경남 양산", "경남 의령", "경남 함안", "경남 창녕",
    "경남 고성", "경남 남해", "경남 하동", "경남 산청", "경남 함양",
    "경남 거창", "경남 합천",
]

# 전국 모드: 모든 도시를 합침
ALL_REGIONS = []
for city_districts in CITY_TO_DISTRICTS.values():
    ALL_REGIONS.extend(city_districts)
ALL_REGIONS.extend(EXTRA_REGIONS)


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


def _emit_progress(keyword=None, region=None, business=None):
    """현재 진행 상황을 stdout에 JSON 출력 (Node.js가 파싱해서 DB에 저장)"""
    try:
        print(json.dumps({
            'progress': {
                'keyword': keyword,
                'region': region,
                'business': business,
            }
        }, ensure_ascii=False), flush=True)
    except Exception:
        pass


def _emit_skip(region, keyword, business_name, reason):
    """스킵 로그를 stdout에 JSON 출력"""
    try:
        print(json.dumps({
            'skipped': {
                'region': region,
                'keyword': keyword,
                'business': business_name,
                'reason': reason,
            }
        }, ensure_ascii=False), flush=True)
    except Exception:
        pass


def _emit_log(message):
    """일반 로그 메시지"""
    try:
        print(json.dumps({'log': message}, ensure_ascii=False), flush=True)
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

    # 조기 종료: 연속 50개 지역에서 새 업체 0개면 더 이상 찾을 게 없다고 판단
    # (이전 15 → 50으로 증가: 중복 제거로 인한 성급한 종료 방지)
    empty_streak = 0
    MAX_EMPTY_STREAK = 50

    # 업체당 최대 처리 시간 (초). 이걸 초과하면 hang으로 판단
    PER_BUSINESS_TIMEOUT = 60
    # 검색 페이지 로드 최대 시간
    PER_REGION_TIMEOUT = 30

    async with create_browser(headed=False) as (browser, context, page):
        # 브라우저 재시작이 필요한 경우를 위한 변수
        need_browser_restart = False

        for keyword in search_keywords:
            if len(results) >= target:
                break
            # 새 키워드 시도 시 empty_streak 초기화
            # (이전 키워드가 50번 빈 결과여도 다음 변형 키워드는 처음부터 기회 받음)
            empty_streak = 0

            for ri, region in enumerate(regions):
                if len(results) >= target:
                    break
                if empty_streak >= MAX_EMPTY_STREAK:
                    logging.warning(f"키워드 '{keyword}' 연속 {MAX_EMPTY_STREAK}개 지역 빈 결과 → 다음 키워드로")
                    _emit_log(f"키워드 '{keyword}' {MAX_EMPTY_STREAK}개 지역 빈 결과 → 다음 키워드로")
                    break
                region_found_before = len(results)

                # 브라우저 재시작: context + page 전부 새로 생성
                if need_browser_restart:
                    try:
                        try:
                            await context.close()
                        except Exception:
                            pass
                        context = await browser.new_context(
                            viewport={"width": 1920, "height": 1080},
                            locale="ko-KR",
                            timezone_id="Asia/Seoul",
                        )
                        page = await context.new_page()
                        need_browser_restart = False
                        _emit_log("브라우저 context+page 재생성 완료")
                    except Exception as e:
                        _emit_log(f"브라우저 재생성 실패: {e} → 종료")
                        break

                # 진행 상황 출력 (실시간 추적용)
                _emit_progress(keyword=keyword, region=region, business=None)

                try:
                    # 검색 페이지 로드 (timeout 보호)
                    sf = await asyncio.wait_for(
                        navigate_to_search(page, region, keyword),
                        timeout=PER_REGION_TIMEOUT
                    )
                    entries = await collect_all_entries(page, sf, per_region)
                    if not entries:
                        continue
                    sf = await get_search_frame(page)

                    region_skipped = False
                    for idx, entry in enumerate(entries):
                        if len(results) >= target:
                            break
                        # heartbeat: 5건마다 진행 상황을 stderr로 출력 (UI/로그에서 멈춤 여부 확인용)
                        if idx % 5 == 0:
                            logging.warning(f"[진행] {region} '{keyword}' {idx+1}/{len(entries)} (누적 {len(results)})")

                        # 진행 상황: 현재 처리 중인 업체
                        _emit_progress(keyword=keyword, region=region, business=entry.get('name'))

                        biz = None
                        try:
                            # 업체당 60초 timeout
                            biz = await asyncio.wait_for(
                                click_and_extract(
                                    page, sf, entry, category,
                                    context=context, search_region=region
                                ),
                                timeout=PER_BUSINESS_TIMEOUT
                            )
                        except asyncio.TimeoutError:
                            entry_name = entry.get('name', '?')
                            _emit_skip(region, keyword, entry_name, 'timeout')
                            logging.warning(f"[멈춤 감지] {region} '{keyword}' '{entry_name}' → 지역 스킵")
                            # timeout 후 브라우저 상태가 꼬일 수 있음 → 페이지 재생성
                            need_browser_restart = True
                            try:
                                await page.close()
                            except Exception:
                                pass
                            region_skipped = True
                            break
                        except Exception as e:
                            err_str = str(e).lower()
                            if 'closed' in err_str or 'target' in err_str:
                                # TargetClosedError → 페이지 재생성 필요
                                _emit_skip(region, keyword, entry.get('name', '?'), 'browser_closed')
                                need_browser_restart = True
                                region_skipped = True
                                break
                            err_type = 'frame_detached' if 'detached' in err_str else 'other'
                            entry_name = entry.get('name', '?')
                            _emit_skip(region, keyword, entry_name, err_type)
                            logging.warning(f"[처리 오류] {region} '{entry_name}': {e}")
                            continue

                        if biz:
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

                                if len(results) % 10 == 0:
                                    _save_intermediate(results, result_path)
                                    save_history(history_ids)

                        await asyncio.sleep(random.uniform(DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX))
                        if (idx + 1) % LONG_PAUSE_INTERVAL == 0:
                            await asyncio.sleep(random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX))

                        try:
                            sf = await asyncio.wait_for(get_search_frame(page), timeout=10)
                        except:
                            try:
                                await asyncio.wait_for(
                                    navigate_to_search(page, region, keyword),
                                    timeout=PER_REGION_TIMEOUT
                                )
                                sf = await asyncio.wait_for(get_search_frame(page), timeout=10)
                            except Exception:
                                _emit_skip(region, keyword, None, 'iframe_failed')
                                region_skipped = True
                                break

                    if region_skipped:
                        # 다음 지역으로
                        pass

                except asyncio.TimeoutError:
                    # 검색 페이지 로드 자체가 timeout
                    _emit_skip(region, keyword, None, 'region_load_timeout')
                    logging.warning(f"[지역 로드 멈춤] {region} '{keyword}' → 스킵")
                except Exception as e:
                    err_type = 'iframe_failed' if 'iframe' in str(e).lower() else 'other'
                    _emit_skip(region, keyword, None, err_type)
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
