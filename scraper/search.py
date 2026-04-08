"""네이버 맵 검색결과 페이지 탐색 및 파싱 모듈"""

import asyncio
import logging
from urllib.parse import quote
from playwright.async_api import Page, Frame

from config import NAVER_MAP_URL, PAGE_LOAD_TIMEOUT, ELEMENT_TIMEOUT

logger = logging.getLogger(__name__)


async def get_search_frame(page: Page) -> Frame:
    """검색결과 iframe을 찾아 반환한다."""
    iframe_el = await page.query_selector("#searchIframe")
    if iframe_el:
        frame = await iframe_el.content_frame()
        if frame:
            return frame

    for f in page.frames:
        if "pcmap.place.naver.com" in f.url and ("list" in f.url or "search" in f.url):
            return f

    frame = page.frame("searchIframe")
    if frame:
        return frame

    raise RuntimeError("searchIframe을 찾을 수 없습니다")


async def get_entry_frame(page: Page) -> Frame | None:
    """상세정보 iframe(entryIframe)을 찾아 반환한다."""
    iframe_el = await page.query_selector("#entryIframe")
    if iframe_el:
        frame = await iframe_el.content_frame()
        if frame:
            return frame

    for f in page.frames:
        if "pcmap.place.naver.com" in f.url and "/home" in f.url:
            return f

    frame = page.frame("entryIframe")
    if frame:
        return frame

    return None


async def navigate_to_search(page: Page, region: str, category: str) -> Frame:
    """네이버 맵 검색 페이지로 이동하고 검색결과 iframe을 반환한다."""
    query = f"{region} {category}"
    url = NAVER_MAP_URL.format(query=quote(query))

    logger.info(f"검색 시작: '{query}' -> {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    await asyncio.sleep(5)

    # searchIframe이 로드될 때까지 재시도 (최대 3회)
    search_frame = None
    for attempt in range(3):
        try:
            search_frame = await get_search_frame(page)
            break
        except RuntimeError:
            logger.warning(f"searchIframe 로드 대기 중... ({attempt + 1}/3)")
            await asyncio.sleep(5)

    if search_frame is None:
        raise RuntimeError("searchIframe을 찾을 수 없습니다")

    try:
        await search_frame.wait_for_selector(
            "#_pcmap_list_scroll_container", timeout=ELEMENT_TIMEOUT
        )
    except Exception:
        logger.warning("리스트 컨테이너 대기 중...")
        await asyncio.sleep(5)
        # iframe이 바뀌었을 수 있으므로 재확인
        try:
            search_frame = await get_search_frame(page)
            await search_frame.wait_for_selector("li", timeout=ELEMENT_TIMEOUT)
        except Exception:
            pass

    logger.info("검색결과 로드 완료")
    return search_frame


async def parse_entries(search_frame: Frame) -> list[dict]:
    """현재 보이는 검색결과 목록에서 업체 항목들을 파싱한다."""
    entries = await search_frame.evaluate(r"""
        () => {
            const results = [];
            let items = document.querySelectorAll('#_pcmap_list_scroll_container li');
            if (items.length === 0) {
                items = document.querySelectorAll('li');
            }

            for (let i = 0; i < items.length; i++) {
                const li = items[i];
                const text = li.textContent || '';
                if (text.length < 30) continue;

                let name = '';
                // 방법 1: q2LdB 클래스 (현재 네이버 업체명 셀렉터)
                const q2Span = li.querySelector('[class*="q2LdB"]');
                if (q2Span) {
                    name = q2Span.textContent.trim();
                }
                // 방법 2: TYaxT 클래스 (이전 버전 호환)
                if (!name) {
                    const nameSpan = li.querySelector('[class*="TYaxT"]');
                    if (nameSpan) {
                        name = nameSpan.textContent.trim();
                    }
                }
                // 방법 3: YwYLL 클래스 (청소/이사 등 서비스 업종)
                if (!name) {
                    const ywSpan = li.querySelector('[class*="YwYLL"]');
                    if (ywSpan) {
                        name = ywSpan.textContent.trim();
                    }
                }
                // 방법 4: uD1F4 클래스의 a 태그 (현재 네이버 업체 링크)
                if (!name) {
                    const nameLink = li.querySelector('a[class*="uD1F4"]');
                    if (nameLink) {
                        // 링크 텍스트에서 카테고리(치과, 미용실 등) 부분 제거
                        const linkText = nameLink.textContent.trim();
                        const q2 = nameLink.querySelector('[class*="q2LdB"]');
                        if (q2) {
                            name = q2.textContent.trim();
                        } else {
                            name = linkText;
                        }
                    }
                }
                // 방법 5: 첫 번째 링크의 span에서 추출 (최후 수단)
                if (!name) {
                    const firstLink = li.querySelector('a');
                    if (firstLink) {
                        const spans = firstLink.querySelectorAll('span');
                        for (const span of spans) {
                            const t = span.textContent.trim();
                            // 오탐 제외: place_blind, 이미지수, place_thumb 등
                            if (t.length > 1 && t.length < 50 &&
                                !t.includes('네이버') &&
                                !t.includes('이미지') &&
                                !span.classList.contains('place_blind') &&
                                !span.classList.contains('place_thumb_count') &&
                                !span.className.includes('place_thumb') &&
                                !/^\d+$/.test(t)) {
                                name = t;
                                break;
                            }
                        }
                    }
                }

                if (name && name.length > 0) {
                    // 광고/오탐 항목 필터링
                    if (/^이미지\s*수?\s*\d*$/.test(name)) continue;
                    if (/^이미지\s/.test(name)) continue;
                    if (name === '광고' || name === 'AD') continue;
                    if (/^\d+$/.test(name)) continue;  // 순수 숫자만
                    if (name.length < 2) continue;  // 1글자 이름 제외
                    if (/^(place_blind|네이버|더보기|닫기|사진|지도)/.test(name)) continue;
                    results.push({name: name, index: i});
                }
            }
            return results;
        }
    """)

    logger.info(f"현재 화면에서 {len(entries)}개 업체 발견")
    return entries


async def click_entry_by_name(search_frame: Frame, name: str) -> bool:
    """업체명으로 검색결과에서 해당 항목을 찾아 스크롤 후 클릭한다.

    인덱스 대신 이름으로 찾으므로 가상 스크롤 환경에서도 안정적으로 동작한다.
    """
    try:
        clicked = await search_frame.evaluate("""
            (targetName) => {
                const container = document.querySelector('#_pcmap_list_scroll_container');
                if (!container) return false;

                // 먼저 컨테이너를 맨 위로 스크롤
                container.scrollTop = 0;

                // 이름으로 항목 찾기 (현재 DOM에서)
                function findAndClick() {
                    const items = container.querySelectorAll('li');
                    for (const li of items) {
                        if (li.textContent.length < 30) continue;
                        // 여러 셀렉터로 업체명 찾기
                        let nameText = '';
                        const selectors = ['[class*="q2LdB"]', '[class*="TYaxT"]', '[class*="YwYLL"]'];
                        for (const sel of selectors) {
                            const el = li.querySelector(sel);
                            if (el) { nameText = el.textContent.trim(); break; }
                        }
                        if (!nameText) {
                            const firstLink = li.querySelector('a');
                            if (firstLink) {
                                const spans = firstLink.querySelectorAll('span');
                                for (const span of spans) {
                                    const t = span.textContent.trim();
                                    if (t === targetName) {
                                        span.closest('a')?.click() || li.querySelector('a')?.click();
                                        return true;
                                    }
                                }
                            }
                        }
                        if (nameText === targetName) {
                            const clickTarget = li.querySelector('a') || li;
                            li.scrollIntoView({block: 'center', behavior: 'instant'});
                            clickTarget.click();
                            return true;
                        }
                    }
                    return false;
                }

                return findAndClick();
            }
        """, name)
        return clicked
    except Exception as e:
        logger.debug(f"이름으로 클릭 실패 ('{name}'): {e}")
        return False


async def scroll_to_entry_and_click(search_frame: Frame, name: str) -> bool:
    """항목을 찾을 때까지 점진적으로 스크롤하면서 클릭을 시도한다.

    가상 스크롤 환경에서 항목이 DOM에 없을 수 있으므로,
    스크롤하면서 항목이 나타날 때까지 반복한다.
    """
    max_scroll_attempts = 20

    # 먼저 맨 위로 스크롤
    await search_frame.evaluate("""
        () => {
            const c = document.querySelector('#_pcmap_list_scroll_container');
            if (c) c.scrollTop = 0;
        }
    """)
    await asyncio.sleep(0.5)

    for attempt in range(max_scroll_attempts):
        # 현재 DOM에서 이름으로 클릭 시도
        clicked = await click_entry_by_name(search_frame, name)
        if clicked:
            return True

        # 못 찾으면 아래로 조금씩 스크롤
        await search_frame.evaluate("""
            () => {
                const c = document.querySelector('#_pcmap_list_scroll_container');
                if (c) c.scrollTop += 300;
            }
        """)
        await asyncio.sleep(0.5)

    logger.warning(f"'{name}' 항목을 스크롤해도 찾지 못함")
    return False


# 하위 호환성을 위해 유지
async def click_entry_by_index(search_frame: Frame, index: int) -> bool:
    """인덱스 기반 클릭 (레거시). scroll_to_entry_and_click 사용 권장."""
    try:
        clicked = await search_frame.evaluate(f"""
            (idx) => {{
                let items = document.querySelectorAll('#_pcmap_list_scroll_container li');
                if (items.length === 0) items = document.querySelectorAll('li');

                for (let i = 0, liIdx = 0; i < items.length; i++) {{
                    const li = items[i];
                    if (li.textContent.length < 30) continue;
                    const nameSpan = li.querySelector('[class*="TYaxT"]');
                    const firstLink = li.querySelector('a');
                    if (nameSpan || (firstLink && li.textContent.length > 30)) {{
                        if (liIdx === idx) {{
                            li.scrollIntoView({{block: 'center'}});
                            const clickTarget = li.querySelector('a') || li;
                            clickTarget.click();
                            return true;
                        }}
                        liIdx++;
                    }}
                }}
                return false;
            }}
        """, index)
        return clicked
    except Exception as e:
        logger.debug(f"클릭 실패 (index={index}): {e}")
        return False


async def scroll_for_more(search_frame: Frame, previous_count: int) -> bool:
    """검색결과를 스크롤하여 추가 항목을 로드한다."""
    await search_frame.evaluate("""
        () => {
            const container = document.querySelector('#_pcmap_list_scroll_container');
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        }
    """)
    await asyncio.sleep(2)

    new_entries = await parse_entries(search_frame)
    if len(new_entries) > previous_count:
        logger.info(f"스크롤 후 항목 증가: {previous_count} -> {len(new_entries)}")
        return True
    return False


async def check_and_click_next_page(search_frame: Frame) -> bool:
    """페이지네이션 버튼이 있으면 다음 페이지로 이동한다."""
    try:
        clicked = await search_frame.evaluate("""
            () => {
                const pageButtons = document.querySelectorAll('[class*="pagination"] a, [class*="page"] a');
                for (const btn of pageButtons) {
                    if (btn.getAttribute('aria-disabled') === 'true') continue;
                    const cls = btn.className || '';
                    const text = btn.textContent.trim();
                    if (cls.includes('next') || text === '다음') {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if clicked:
            await asyncio.sleep(2)
            logger.info("다음 페이지로 이동")
        return clicked
    except Exception as e:
        logger.debug(f"페이지네이션 처리 중 오류: {e}")
        return False


async def collect_all_entries(
    page: Page,
    search_frame: Frame,
    max_results: int,
) -> list[dict]:
    """스크롤 및 페이지네이션을 통해 업체 이름 목록을 수집한다."""
    all_entries = []
    seen_names = set()
    no_new_count = 0
    max_no_new = 3

    while len(all_entries) < max_results and no_new_count < max_no_new:
        entries = await parse_entries(search_frame)

        new_count = 0
        for entry in entries:
            if entry["name"] not in seen_names:
                seen_names.add(entry["name"])
                all_entries.append(entry)
                new_count += 1

        if new_count == 0:
            no_new_count += 1
        else:
            no_new_count = 0

        if len(all_entries) >= max_results:
            break

        prev_count = len(entries)
        scrolled = await scroll_for_more(search_frame, prev_count)

        if not scrolled:
            has_next = await check_and_click_next_page(search_frame)
            if has_next:
                await asyncio.sleep(3)
                try:
                    search_frame = await get_search_frame(page)
                except Exception:
                    pass
                no_new_count = 0
            else:
                no_new_count += 1

    result = all_entries[:max_results]
    logger.info(f"총 {len(result)}개 업체 수집 완료")
    return result
