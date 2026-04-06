"""디버그: 실제 플레이스 페이지에서 어떤 정보를 추출할 수 있는지 확인"""
import asyncio
import logging
from scraper.browser import create_browser
from scraper.search import navigate_to_search, collect_all_entries, get_search_frame, get_entry_frame, scroll_to_entry_and_click

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

async def debug():
    async with create_browser(headed=False) as (browser, context, page):
        # 카페 검색 (이메일 0%였던 업종)
        search_frame = await navigate_to_search(page, "서울 강남구", "카페")
        entries = await collect_all_entries(page, search_frame, 3)
        search_frame = await get_search_frame(page)

        for entry in entries[:2]:
            name = entry["name"]
            print(f"\n{'='*60}")
            print(f"업체: {name}")
            print(f"{'='*60}")

            clicked = await scroll_to_entry_and_click(search_frame, name)
            if not clicked:
                print("클릭 실패!")
                continue

            await asyncio.sleep(3)
            entry_frame = await get_entry_frame(page)
            if not entry_frame:
                print("상세 페이지 로드 실패!")
                continue

            await asyncio.sleep(2)

            # 상세 페이지의 모든 링크 수집
            all_links = await entry_frame.evaluate(r"""
                () => {
                    const links = [];
                    document.querySelectorAll('a[href]').forEach(a => {
                        const href = a.href || '';
                        const text = a.textContent?.trim() || '';
                        if (href.startsWith('http') && !href.includes('map.naver.com/p/search')) {
                            links.push({href: href.substring(0, 100), text: text.substring(0, 50)});
                        }
                    });
                    return links;
                }
            """)

            print("\n[모든 링크]")
            for link in all_links:
                print(f"  {link['text']:<30} → {link['href']}")

            # 모든 탭/버튼 찾기
            tabs = await entry_frame.evaluate(r"""
                () => {
                    const tabs = [];
                    const els = document.querySelectorAll('a, button, span[role], div[role]');
                    for (const el of els) {
                        const t = el.textContent?.trim();
                        if (t && t.length < 15 && t.length > 0 && el.offsetParent !== null) {
                            tabs.push(t);
                        }
                    }
                    return [...new Set(tabs)].slice(0, 30);
                }
            """)
            print(f"\n[탭/버튼]: {tabs}")

            # 플레이스 URL 확인
            print(f"\n[Frame URL]: {entry_frame.url}")

            # 전화번호 영역 근처 텍스트
            contact_area = await entry_frame.evaluate(r"""
                () => {
                    const bodyText = document.body?.innerText || '';
                    const lines = bodyText.split('\n').map(l => l.trim()).filter(l => l);
                    // "전화번호", "주소", "홈페이지", "블로그" 등의 라벨 근처 텍스트
                    const keywords = ['전화', '주소', '홈페이지', '블로그', '이메일', 'email', '정보', '소식', '예약', '톡톡'];
                    const found = [];
                    for (let i = 0; i < lines.length; i++) {
                        for (const kw of keywords) {
                            if (lines[i].includes(kw)) {
                                found.push({
                                    line: i,
                                    keyword: kw,
                                    text: lines[i],
                                    next: lines[i+1] || '',
                                    next2: lines[i+2] || '',
                                });
                                break;
                            }
                        }
                    }
                    return found;
                }
            """)
            print("\n[연락처 영역]")
            for c in contact_area:
                print(f"  [{c['keyword']}] {c['text']} → {c['next']} → {c['next2']}")

            search_frame = await get_search_frame(page)
            await asyncio.sleep(2)

asyncio.run(debug())
