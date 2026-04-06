"""업체명 추출 디버그 - 현재 네이버 플레이스 HTML 구조 확인"""
import asyncio, logging
from scraper.browser import create_browser
from scraper.search import navigate_to_search, get_search_frame

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

async def debug():
    async with create_browser(headed=False) as (browser, context, page):
        sf = await navigate_to_search(page, "서울 강남구", "치과")
        await asyncio.sleep(3)

        # 첫 5개 li 항목의 HTML 구조 분석
        result = await sf.evaluate(r"""
            () => {
                const items = document.querySelectorAll('#_pcmap_list_scroll_container li');
                const analysis = [];

                for (let i = 0; i < Math.min(items.length, 5); i++) {
                    const li = items[i];
                    const text = li.textContent || '';
                    if (text.length < 30) continue;

                    // 모든 span의 클래스와 텍스트 수집
                    const spans = [];
                    li.querySelectorAll('span').forEach(span => {
                        const t = span.textContent.trim();
                        if (t.length > 0 && t.length < 60) {
                            spans.push({
                                class: span.className || '(없음)',
                                text: t.substring(0, 40),
                                parent: span.parentElement?.tagName || '?',
                                isHidden: span.classList.contains('place_blind'),
                            });
                        }
                    });

                    // a 태그들
                    const links = [];
                    li.querySelectorAll('a').forEach(a => {
                        const t = a.textContent?.trim() || '';
                        if (t.length > 0 && t.length < 60) {
                            links.push({
                                text: t.substring(0, 40),
                                class: a.className || '(없음)',
                            });
                        }
                    });

                    // TYaxT 셀렉터 확인
                    const tyaxt = li.querySelector('[class*="TYaxT"]');
                    const ywyll = li.querySelector('[class*="YwYLL"]');

                    analysis.push({
                        index: i,
                        TYaxT: tyaxt ? tyaxt.textContent.trim() : null,
                        YwYLL: ywyll ? ywyll.textContent.trim() : null,
                        spans_count: spans.length,
                        first_5_spans: spans.slice(0, 8),
                        first_3_links: links.slice(0, 3),
                    });
                }
                return analysis;
            }
        """)

        for item in result:
            print(f"\n{'='*60}")
            print(f"[항목 {item['index']}]")
            print(f"  TYaxT: {item['TYaxT']}")
            print(f"  YwYLL: {item['YwYLL']}")
            print(f"  spans ({item['spans_count']}개):")
            for s in item['first_5_spans']:
                hidden = " [HIDDEN]" if s['isHidden'] else ""
                print(f"    class={s['class'][:30]:<30} text={s['text']}{hidden}")
            print(f"  links:")
            for l in item['first_3_links']:
                print(f"    class={l['class'][:30]:<30} text={l['text']}")

asyncio.run(debug())
