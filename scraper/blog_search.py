"""네이버 블로그 검색을 통한 업체 정보 수집 모듈

네이버 검색 > 블로그 탭 > 최신순으로 포스트를 순회하며
포스트 본문의 전화번호, 이메일, 플레이스 지도 임베드 정보를 추출한다.
"""

import asyncio
import logging
import re
from urllib.parse import quote
from playwright.async_api import Page, Frame, BrowserContext

from models.business import Business

logger = logging.getLogger(__name__)

BLOG_SEARCH_URL = (
    "https://search.naver.com/search.naver"
    "?ssc=tab.blog.all&sm=tab_opt&query={query}"
    "&nso=so%3Add%2Cp%3Aall&where=blog"
)

PHONE_PATTERN = re.compile(r"0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4}")
PHONE_010_PATTERN = re.compile(r"010[-.\s]?\d{4}[-.\s]?\d{4}")
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


async def _extract_posts_from_page(page: Page) -> list[dict]:
    """현재 페이지에서 블로그 포스트 링크를 추출한다."""
    return await page.evaluate(r"""
        () => {
            const links = [];
            const seen = new Set();
            document.querySelectorAll('a[href*="blog.naver.com"]').forEach(a => {
                const href = a.href;
                const match = href.match(/blog\.naver\.com\/([^/?]+)\/(\d+)/);
                if (match && !seen.has(match[2])) {
                    seen.add(match[2]);
                    const title = a.textContent?.trim()?.substring(0, 100) || '';
                    if (title.length > 3) {
                        links.push({
                            href: href,
                            title: title,
                            blogId: match[1],
                            postId: match[2],
                        });
                    }
                }
            });
            return links;
        }
    """)


async def collect_blog_post_urls(
    page: Page, region: str, category: str, max_posts: int = 50,
) -> list[dict]:
    """블로그 검색 결과에서 포스트 URL 목록을 수집한다.

    네이버 블로그 검색은 무한 스크롤 방식으로 포스트를 누적 로드한다.
    페이지 하단으로 스크롤하면 30개씩 추가 로드됨.

    Returns:
        [{"href": str, "title": str, "blogId": str, "postId": str}]
    """
    query = f"{region} {category}"
    url = BLOG_SEARCH_URL.format(query=quote(query))

    logger.info(f"블로그 검색: '{query}' (최신순)")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    all_posts = []
    seen_post_ids = set()
    no_new_count = 0
    max_no_new = 3  # 3번 연속 새 포스트 없으면 종료
    scroll_count = 0

    while len(all_posts) < max_posts and no_new_count < max_no_new:
        # 현재 페이지에서 포스트 추출
        posts = await _extract_posts_from_page(page)

        new_count = 0
        for post in posts:
            if post["postId"] not in seen_post_ids:
                seen_post_ids.add(post["postId"])
                all_posts.append(post)
                new_count += 1

        if new_count == 0:
            no_new_count += 1
        else:
            no_new_count = 0

        if len(all_posts) >= max_posts:
            break

        # 페이지 하단으로 스크롤하여 추가 로드
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)
        scroll_count += 1

        if scroll_count % 3 == 0:
            logger.info(f"  스크롤 {scroll_count}회... (현재 {len(all_posts)}개)")

    result = all_posts[:max_posts]
    logger.info(f"총 {len(result)}개 블로그 포스트 수집")
    return result


async def extract_from_blog_post(
    context: BrowserContext, post_url: str,
) -> dict:
    """블로그 포스트를 방문하여 업체 정보를 추출한다.

    Returns:
        {
            "business_name": str | None,
            "phones": [str],         # 모든 전화번호
            "phones_010": [str],     # 010 번호만
            "emails": [str],
            "place_id": str | None,  # 네이버 플레이스 ID
            "place_name": str | None,
            "address": str | None,
        }
    """
    result = {
        "business_name": None,
        "phones": [],
        "phones_010": [],
        "emails": [],
        "place_id": None,
        "place_name": None,
        "address": None,
    }

    page = await context.new_page()

    try:
        await page.goto(post_url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(3)

        # mainFrame iframe에서 본문 분석
        for frame in page.frames:
            try:
                frame_data = await frame.evaluate(r"""
                    () => {
                        const text = document.body?.innerText || '';
                        if (text.length < 50) return null;

                        const result = {
                            phones: [],
                            phones010: [],
                            emails: [],
                            placeLinks: [],
                            placeName: null,
                            address: null,
                        };

                        // 전화번호 추출
                        const phoneRe = /0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4}/g;
                        let m;
                        const seenPhones = new Set();
                        while ((m = phoneRe.exec(text)) !== null) {
                            if (!seenPhones.has(m[0])) {
                                seenPhones.add(m[0]);
                                result.phones.push(m[0]);
                                if (m[0].startsWith('010')) {
                                    result.phones010.push(m[0]);
                                }
                            }
                        }

                        // 이메일 추출
                        const emailRe = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;
                        const seenEmails = new Set();
                        while ((m = emailRe.exec(text)) !== null) {
                            const email = m[0].toLowerCase();
                            if (!seenEmails.has(email) &&
                                !email.endsWith('naver.com') &&
                                !email.endsWith('example.com')) {
                                seenEmails.add(email);
                                result.emails.push(m[0]);
                            }
                        }

                        // 플레이스 지도 링크 추출
                        document.querySelectorAll('a[href]').forEach(a => {
                            const href = a.href || '';
                            // map.naver.com/v5/entry/place/{placeId} 패턴
                            const placeMatch = href.match(/(?:place|entry\/place)\/(\d+)/);
                            if (placeMatch) {
                                result.placeLinks.push({
                                    placeId: placeMatch[1],
                                    text: a.textContent?.trim()?.substring(0, 100) || '',
                                });
                            }
                        });

                        // 플레이스 위젯에서 업체명/주소 추출
                        const mapWidget = document.querySelector('.se-placesMap, [class*="se-place"]');
                        if (mapWidget) {
                            const infoEl = mapWidget.querySelector('.se-map-info, [class*="map-info"]');
                            if (infoEl) {
                                const nameEl = infoEl.querySelector('.se-map-title, [class*="title"]');
                                if (nameEl) result.placeName = nameEl.textContent?.trim();

                                const addrEl = infoEl.querySelector('.se-map-address, [class*="address"]');
                                if (addrEl) result.address = addrEl.textContent?.trim();
                            }
                            // 위젯 전체 텍스트에서 이름 추출 시도
                            if (!result.placeName) {
                                const widgetText = mapWidget.textContent?.trim() || '';
                                const lines = widgetText.split('\n').map(l => l.trim()).filter(l => l);
                                if (lines.length > 0) {
                                    // 첫 줄이 주로 업체명
                                    const candidate = lines.find(l => l.length > 1 && l.length < 40 && l !== '지도');
                                    if (candidate) result.placeName = candidate;
                                }
                            }
                        }

                        return result;
                    }
                """)

                if frame_data:
                    result["phones"].extend(frame_data["phones"])
                    result["phones_010"].extend(frame_data["phones010"])
                    result["emails"].extend(frame_data["emails"])

                    if frame_data["placeLinks"]:
                        first_place = frame_data["placeLinks"][0]
                        result["place_id"] = first_place["placeId"]
                        if first_place["text"]:
                            result["place_name"] = first_place["text"]

                    if frame_data["placeName"]:
                        result["place_name"] = frame_data["placeName"]
                    if frame_data["address"]:
                        result["address"] = frame_data["address"]

            except Exception:
                continue

        # 중복 제거
        result["phones"] = list(dict.fromkeys(result["phones"]))
        result["phones_010"] = list(dict.fromkeys(result["phones_010"]))
        result["emails"] = list(dict.fromkeys(result["emails"]))

    except Exception as e:
        logger.debug(f"  포스트 접근 실패: {e}")
    finally:
        await page.close()

    return result


async def get_place_detail(
    context: BrowserContext, place_id: str,
) -> dict:
    """네이버 플레이스 상세 페이지에서 업체 정보를 가져온다."""
    url = f"https://pcmap.place.naver.com/place/{place_id}/home"
    result = {"name": None, "phone": None, "address": None, "category": None}

    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(2)

        detail = await page.evaluate(r"""
            () => {
                const result = {name: '', phone: '', address: '', category: ''};
                const text = document.body?.innerText || '';
                const lines = text.split('\n').map(l => l.trim()).filter(l => l);

                // 업체명 (첫 번째 의미있는 텍스트)
                for (const line of lines) {
                    if (line.length > 1 && line.length < 40 &&
                        !line.includes('이전') && !line.includes('페이지')) {
                        result.name = line;
                        break;
                    }
                }

                for (let i = 0; i < lines.length; i++) {
                    if (lines[i] === '전화번호' && i + 1 < lines.length) {
                        const m = lines[i + 1].match(/0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4}/);
                        if (m) result.phone = m[0];
                    }
                    if (lines[i] === '주소' && i + 1 < lines.length) {
                        const next = lines[i + 1];
                        if (next.length > 5 && !next.startsWith('http')) {
                            result.address = next;
                        }
                    }
                }

                return result;
            }
        """)

        result = detail
    except Exception as e:
        logger.debug(f"  플레이스 상세 접근 실패: {e}")
    finally:
        await page.close()

    return result


async def search_place_by_name(
    context: BrowserContext,
    biz_name: str,
    region: str = "",
) -> dict:
    """업체명으로 네이버 플레이스를 검색하여 전화번호/주소를 가져온다.

    블로그에서 업체명은 찾았지만 번호가 없을 때 보완용.
    pcmap.place.naver.com에 직접 접근하여 iframe 문제 우회.
    """
    from urllib.parse import quote

    result = {"phone": None, "address": None, "place_id": None}
    page = await context.new_page()

    try:
        # map.naver.com에서 검색 (searchIframe → 첫 결과 클릭 → entryIframe)
        query = f"{region} {biz_name}".strip()
        url = f"https://map.naver.com/p/search/{quote(query)}"
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)

        # searchIframe 찾기
        search_frame = None
        iframe_el = await page.query_selector("#searchIframe")
        if iframe_el:
            search_frame = await iframe_el.content_frame()
        if not search_frame:
            for f in page.frames:
                if "pcmap.place.naver.com" in f.url and "list" in f.url:
                    search_frame = f
                    break

        if not search_frame:
            return result

        await asyncio.sleep(2)

        # 첫 번째 업체 클릭 (텍스트 기반 - 셀렉터 변경에 강건)
        clicked = await search_frame.evaluate(r"""
            () => {
                // 방법 1: 스크롤 컨테이너 내 li
                let items = document.querySelectorAll('#_pcmap_list_scroll_container li');
                if (items.length === 0) items = document.querySelectorAll('li');
                for (const li of items) {
                    if (li.textContent.length < 30) continue;
                    const a = li.querySelector('a');
                    if (a) { a.click(); return true; }
                }
                // 방법 2: 아무 링크나 클릭
                const anyLink = document.querySelector('a[href="#"]');
                if (anyLink) { anyLink.click(); return true; }
                return false;
            }
        """)

        if not clicked:
            return result

        await asyncio.sleep(4)

        # entryIframe 찾기
        entry_frame = None
        entry_el = await page.query_selector("#entryIframe")
        if entry_el:
            entry_frame = await entry_el.content_frame()
        if not entry_frame:
            for f in page.frames:
                if "pcmap.place.naver.com" in f.url and "/home" in f.url:
                    entry_frame = f
                    break

        if not entry_frame:
            return result

        await asyncio.sleep(2)

        # 상세 페이지 텍스트에서 정보 추출
        detail = await entry_frame.evaluate(r"""
            () => {
                const r = {phone: null, address: null, place_id: null};
                const text = document.body?.innerText || '';
                const lines = text.split('\n').map(l => l.trim()).filter(l => l);

                for (let i = 0; i < lines.length; i++) {
                    if (lines[i] === '전화번호' && i + 1 < lines.length) {
                        const m = lines[i+1].match(/0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4}/);
                        if (m) r.phone = m[0];
                    }
                    if (lines[i] === '주소' && i + 1 < lines.length) {
                        const next = lines[i+1];
                        if (next.length > 5 && !next.startsWith('http'))
                            r.address = next;
                    }
                }

                const urlMatch = window.location.href.match(/place\/(\d+)/);
                if (urlMatch) r.place_id = urlMatch[1];

                return r;
            }
        """)

        result = detail
        if result.get("phone"):
            logger.info(f"  플레이스 검색으로 번호 발견: {result['phone']}")

    except Exception as e:
        logger.debug(f"  플레이스 검색 실패 ({biz_name}): {e}")
    finally:
        await page.close()

    return result


async def scrape_blog_search(
    context: BrowserContext,
    page: Page,
    region: str,
    category: str,
    max_posts: int,
    delay_min: float,
    delay_max: float,
    stop_flag=None,
    progress_callback=None,
    log_callback=None,
) -> list[Business]:
    """블로그 검색 기반 업체 정보 수집 메인 로직.

    Args:
        stop_flag: 중지 여부를 반환하는 callable (lambda: self.should_stop)
        progress_callback: 진행률 콜백 (current, total, message)
        log_callback: 로그 콜백

    Returns:
        수집된 Business 리스트
    """
    import random
    from config import LONG_PAUSE_INTERVAL, LONG_PAUSE_MIN, LONG_PAUSE_MAX

    # 1단계: 블로그 포스트 URL 수집
    posts = await collect_blog_post_urls(page, region, category, max_posts)
    if not posts:
        logger.warning("블로그 검색 결과가 없습니다")
        return []

    # 2단계: 각 포스트 방문하여 정보 추출
    businesses = []
    seen_place_ids = set()
    seen_names = set()

    for idx, post in enumerate(posts):
        # 중지 체크
        if stop_flag and stop_flag():
            logger.info("사용자에 의해 중단됨")
            break

        # 진행률 업데이트
        if progress_callback:
            progress_callback(idx + 1, len(posts), f"포스트 {idx+1}/{len(posts)} 처리 중...")

        try:
            # 이모지 등 인코딩 문제 방지
            safe_title = post['title'][:50].encode('utf-8', errors='replace').decode('utf-8')
            logger.info(f"[{idx + 1}/{len(posts)}] 블로그 포스트: {safe_title}")

            post_data = await extract_from_blog_post(context, post["href"])

            # 플레이스 ID가 있으면 상세 정보 조회
            biz_name = post_data.get("place_name")
            biz_phone = post_data["phones"][0] if post_data["phones"] else None
            biz_phone_010 = post_data["phones_010"][0] if post_data["phones_010"] else None
            biz_email = post_data["emails"][0] if post_data["emails"] else None
            biz_address = post_data.get("address")
            place_id = post_data.get("place_id")

            if place_id and place_id not in seen_place_ids:
                seen_place_ids.add(place_id)

                # 플레이스 페이지에서 정확한 정보 가져오기
                logger.info(f"  플레이스 상세 조회 (ID: {place_id})")
                place_detail = await get_place_detail(context, place_id)

                if place_detail.get("name"):
                    biz_name = place_detail["name"]
                if place_detail.get("phone") and not biz_phone:
                    biz_phone = place_detail["phone"]
                if place_detail.get("address"):
                    biz_address = place_detail["address"]

            # 업체명이 없으면 건너뛰기
            if not biz_name:
                logger.debug(f"  업체명 없음, 건너뛰기")
                await asyncio.sleep(random.uniform(delay_min, delay_max))
                continue

            # 중복 체크
            if biz_name in seen_names:
                logger.debug(f"  중복 업체: {biz_name}")
                await asyncio.sleep(random.uniform(delay_min, delay_max))
                continue
            seen_names.add(biz_name)

            # 번호가 없으면 업체명으로 네이버 플레이스 재검색
            if not biz_phone:
                logger.info(f"  번호 없음 → '{biz_name}' 플레이스 검색 중...")
                place_result = await search_place_by_name(context, biz_name, region)

                # 못 찾으면 지점명 빼고 재시도
                if not place_result.get("phone"):
                    core_name = re.sub(
                        r'\s*([\w]*점|[\w]*호점|[\w]*지점)$', '', biz_name
                    ).strip()
                    if core_name and core_name != biz_name:
                        logger.info(f"  재시도 → '{core_name}' 검색 중...")
                        place_result = await search_place_by_name(
                            context, core_name, region
                        )

                if place_result.get("phone"):
                    biz_phone = place_result["phone"]
                if place_result.get("address") and not biz_address:
                    biz_address = place_result["address"]
                if place_result.get("place_id") and not place_id:
                    place_id = place_result["place_id"]

            # 블로그 URL에서 네이버 아이디 추출
            naver_id = None
            blog_href = post.get("href", "")
            _id_match = re.match(r"https?://blog\.naver\.com/([^/?]+)", blog_href)
            if _id_match:
                naver_id = _id_match.group(1)

            biz = Business(
                name=biz_name,
                phone=biz_phone,
                personal_phone=biz_phone_010,
                email=biz_email,
                naver_id=naver_id,
                address=biz_address,
                category=category,
                blog_url=blog_href,
                place_id=place_id,
            )

            logger.info(
                f"  수집: {biz_name} | 전화: {biz_phone or '-'} | "
                f"010: {biz_phone_010 or '-'} | 이메일: {biz_email or '-'}"
            )
            businesses.append(biz)

        except Exception as e:
            logger.warning(f"  포스트 처리 중 오류 (건너뛰기): {e}")

        # 딜레이
        await asyncio.sleep(random.uniform(delay_min, delay_max))

        # 장기 대기
        if (idx + 1) % LONG_PAUSE_INTERVAL == 0 and idx + 1 < len(posts):
            pause = random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX)
            logger.info(f"차단 방지 대기 {pause:.0f}초...")
            await asyncio.sleep(pause)

    logger.info(f"블로그 검색으로 {len(businesses)}개 업체 수집 완료")
    return businesses
