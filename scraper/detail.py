"""업체 상세페이지에서 전화번호/이메일/주소를 추출하는 모듈"""

import asyncio
import logging
import re
from playwright.async_api import Page, Frame

from config import ELEMENT_TIMEOUT
from models.business import Business

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"(0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4})")


async def extract_detail_from_frame(frame: Frame) -> dict:
    """상세 iframe에서 전화번호, 주소, 이메일, 홈페이지를 추출한다.

    네이버 플레이스 상세 페이지의 텍스트 구조 기반으로 추출:
    - "전화번호" 라벨 다음에 전화번호
    - "주소" 라벨 다음에 주소
    - 이메일 패턴 검색
    """
    detail = await frame.evaluate(r"""
        () => {
            const result = {phone: '', address: '', email: '', homepage: '', category: ''};
            const bodyText = document.body?.innerText || '';
            const lines = bodyText.split('\n').map(l => l.trim()).filter(l => l.length > 0);

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];

                // 전화번호: "전화번호" 라벨 다음 줄
                if (line === '전화번호' && i + 1 < lines.length) {
                    const next = lines[i + 1];
                    const phoneMatch = next.match(/0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4}/);
                    if (phoneMatch) {
                        result.phone = phoneMatch[0];
                    }
                }

                // 주소: "주소" 라벨 다음 줄
                if (line === '주소' && i + 1 < lines.length) {
                    const next = lines[i + 1];
                    if (next.length > 5 && !next.startsWith('http')) {
                        result.address = next;
                    }
                }

                // 홈페이지
                if (line === '홈페이지' && i + 1 < lines.length) {
                    const next = lines[i + 1];
                    if (next.startsWith('http')) {
                        result.homepage = next;
                    }
                }
            }

            // 전화번호 보강: 라벨 못 찾은 경우 전체 텍스트에서 추출
            if (!result.phone) {
                // "문의전화", "연락처", "Tel" 등의 패턴
                const phonePatterns = bodyText.match(/(?:문의전화|연락처|전화|Tel|TEL|☎)\s*[:.]?\s*(0\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4})/);
                if (phonePatterns) {
                    result.phone = phonePatterns[1];
                }
            }

            // 주소 보강: 라벨 못 찾은 경우 텍스트 패턴으로 추출
            if (!result.address) {
                for (const line of lines) {
                    // 시/도로 시작하는 주소 패턴
                    if (/^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)/.test(line)
                        && line.length > 8 && line.length < 80
                        && (line.includes('구') || line.includes('시') || line.includes('군'))
                        && !line.includes('검색') && !line.includes('네이버')) {
                        result.address = line.replace(/복사$/, '').replace(/^주소\s*/, '').trim();
                        break;
                    }
                }
            }

            // 이메일: 여러 방법으로 탐색
            // 방법 1: mailto: 링크 (가장 신뢰도 높음)
            const mailtoLinks = document.querySelectorAll('a[href^="mailto:"]');
            for (const a of mailtoLinks) {
                const href = (a.href || '').replace('mailto:', '').split('?')[0].trim();
                if (href.includes('@') && !href.endsWith('naver.com')) {
                    result.email = href;
                    break;
                }
            }

            // 방법 2: 전체 텍스트에서 패턴 검색
            if (!result.email) {
                const emailRegex = /[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/g;
                const allEmails = bodyText.match(emailRegex) || [];
                const ignoredDomains = ['naver.com', 'example.com', 'navercorp.com',
                    'google.com', 'apple.com', 'naver.net', 'sentry.io',
                    'w3.org', 'schema.org', 'wixpress.com'];
                const ignoredPrefixes = ['help', 'support', 'admin', 'noreply', 'no-reply', 'postmaster'];
                for (const email of allEmails) {
                    const lower = email.toLowerCase();
                    const domain = lower.split('@')[1] || '';
                    const prefix = lower.split('@')[0] || '';
                    if (ignoredDomains.some(d => domain === d)) continue;
                    if (ignoredPrefixes.some(p => prefix.startsWith(p))) continue;
                    if (prefix.length < 2 || email.length > 60) continue;
                    if (/\.(png|jpg|gif|svg|css|js)/.test(lower)) continue;
                    result.email = email;
                    break;
                }
            }

            // 방법 3: 숨겨진 요소의 텍스트, data 속성에서 탐색
            if (!result.email) {
                const allElements = document.querySelectorAll('span, div, p, a, td');
                for (const el of allElements) {
                    const text = el.textContent?.trim() || '';
                    if (text.length > 5 && text.length < 60 && text.includes('@') && text.includes('.')) {
                        const m = text.match(/[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}/);
                        if (m && !m[0].toLowerCase().endsWith('naver.com')) {
                            result.email = m[0];
                            break;
                        }
                    }
                }
            }

            // 방법 4: JSON-LD 구조화 데이터
            if (!result.email) {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const data = JSON.parse(s.textContent);
                        if (data.email) { result.email = data.email; break; }
                        if (data.contactPoint?.email) { result.email = data.contactPoint.email; break; }
                    } catch {}
                }
            }

            // 카테고리: 업체명 바로 뒤에 오는 짧은 텍스트
            // 보통 "업체명카테고리" 또는 "업체명\n카테고리" 형태
            const nameEl = document.querySelector('[class*="GHAhO"]')
                || document.querySelector('h2')
                || document.querySelector('[class*="title"]');
            if (nameEl) {
                const sibling = nameEl.nextElementSibling;
                if (sibling) {
                    const catText = sibling.textContent?.trim();
                    if (catText && catText.length < 30) {
                        result.category = catText;
                    }
                }
            }

            // 전화번호 백업: span 요소에서 직접 추출
            if (!result.phone) {
                const allSpans = document.querySelectorAll('span');
                for (const span of allSpans) {
                    const t = span.textContent?.trim() || '';
                    if (/^0\d{1,2}-\d{3,4}-\d{4}$/.test(t)) {
                        result.phone = t;
                        break;
                    }
                }
            }

            return result;
        }
    """)

    return detail


async def click_and_extract(
    page: Page,
    search_frame: Frame,
    entry: dict,
    search_category: str,
    context=None,
    deep_search: bool = False,
    search_region: str = "",
) -> Business:
    """검색결과에서 업체를 클릭하고 상세 정보를 추출한다.

    Args:
        page: Playwright 페이지
        search_frame: 검색결과 iframe
        entry: 업체 항목
        search_category: 검색 카테고리
        context: BrowserContext (deep_search 시 블로그 방문용)
        deep_search: True면 블로그/홈페이지에서 추가 연락처 탐색
    """
    from scraper.search import scroll_to_entry_and_click, get_entry_frame

    name = entry["name"]

    try:
        # 업체명으로 스크롤+클릭 (가상 스크롤 환경 대응)
        clicked = await scroll_to_entry_and_click(search_frame, name)
        if not clicked:
            logger.warning(f"'{name}' 클릭 실패")
            return Business(name=name, category=search_category)

        await asyncio.sleep(1.5)

        # 상세 iframe 대기
        entry_frame = await get_entry_frame(page)
        if entry_frame is None:
            logger.warning(f"'{name}' 상세 페이지 로드 실패")
            return Business(name=name, category=search_category)

        # 상세 컨텐츠 로드 대기
        await asyncio.sleep(1)

        # /photo 페이지로 열린 경우 /home으로 이동
        try:
            frame_url = entry_frame.url
            if "/photo" in frame_url:
                home_url = frame_url.replace("/photo", "/home").split("?")[0]
                await entry_frame.goto(home_url, wait_until="networkidle", timeout=8000)
                await asyncio.sleep(1)
        except Exception:
            pass

        # 상세 정보 추출
        detail = await extract_detail_from_frame(entry_frame)

        # 이메일 못 찾으면 '정보' 탭 클릭 후 재시도
        if not detail.get("email"):
            try:
                tab_clicked = await entry_frame.evaluate(r"""
                    () => {
                        const spans = document.querySelectorAll('span, a, div');
                        for (const el of spans) {
                            const t = el.textContent?.trim();
                            if (t === '정보' && el.offsetParent !== null) {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if tab_clicked:
                    await asyncio.sleep(1)
                    # '더보기' 버튼도 클릭
                    await entry_frame.evaluate(r"""
                        () => {
                            const btns = document.querySelectorAll('a, button, span');
                            for (const el of btns) {
                                const t = el.textContent?.trim();
                                if (t === '더보기' || t === '펼치기') {
                                    el.click();
                                    return;
                                }
                            }
                        }
                    """)
                    await asyncio.sleep(1)
                    detail2 = await extract_detail_from_frame(entry_frame)
                    if detail2.get("email"):
                        detail["email"] = detail2["email"]
                    if detail2.get("phone") and not detail.get("phone"):
                        detail["phone"] = detail2["phone"]
                    if detail2.get("address") and not detail.get("address"):
                        detail["address"] = detail2["address"]
            except Exception:
                pass

        category = detail.get("category") or search_category
        email = detail.get("email") or None
        personal_phone = None
        blog_url = None
        homepage_url = None

        naver_id = None

        # 네이버아이디 추출 (플레이스 상세 페이지에서 직접)
        try:
            naver_id_from_page = await entry_frame.evaluate(r"""
                () => {
                    // 방법 1: 블로그 링크에서 추출
                    const blogLinks = document.querySelectorAll('a[href*="blog.naver.com"]');
                    for (const a of blogLinks) {
                        const match = a.href.match(/blog\.naver\.com\/([a-zA-Z0-9_-]+)/);
                        const excluded = ['PostView', 'PostList', 'prologue', 'place',
                            'home', 'search', 'map', 'entry', 'comment', 'guestbook'];
                        if (match && !excluded.includes(match[1]) && match[1].length > 2) {
                            return match[1];
                        }
                    }

                    // 방법 2: 톡톡 링크에서 추출
                    const talkLinks = document.querySelectorAll('a[href*="talk.naver.com"], a[href*="talktalk"]');
                    for (const a of talkLinks) {
                        const match = a.href.match(/talk\.naver\.com\/[^/]*\/([a-zA-Z0-9_-]+)/);
                        if (match) return match[1];
                    }

                    // 방법 3: 네이버 예약 링크에서 추출
                    const bookLinks = document.querySelectorAll('a[href*="booking.naver.com"]');
                    for (const a of bookLinks) {
                        const match = a.href.match(/booking\.naver\.com\/[^/]*\/([a-zA-Z0-9_-]+)/);
                        if (match) return match[1];
                    }

                    // 방법 4: 스마트스토어 링크에서 추출
                    const storeLinks = document.querySelectorAll('a[href*="smartstore.naver.com"]');
                    for (const a of storeLinks) {
                        const match = a.href.match(/smartstore\.naver\.com\/([a-zA-Z0-9_-]+)/);
                        if (match && match[1] !== 'main') return match[1];
                    }

                    // 방법 5: 플레이스 페이지 URL에서 place ID 추출 (네이버아이디는 아니지만 식별용)
                    // (이건 naver_id가 아니라 place_id이므로 별도 처리)

                    // 방법 6: 전체 텍스트에서 네이버 아이디 패턴 탐색
                    const bodyText = document.body?.innerText || '';
                    const lines = bodyText.split('\n').map(l => l.trim());
                    for (let i = 0; i < lines.length; i++) {
                        if (lines[i] === '블로그' && i + 1 < lines.length) {
                            const next = lines[i + 1];
                            if (next.includes('blog.naver.com')) {
                                const m = next.match(/blog\.naver\.com\/([a-zA-Z0-9_-]+)/);
                                if (m) return m[1];
                            }
                        }
                    }

                    return null;
                }
            """)
            if naver_id_from_page:
                naver_id = naver_id_from_page
        except Exception:
            pass

        # place_id 추출 (entryIframe URL에서)
        place_id = None
        try:
            frame_url = entry_frame.url
            place_match = re.search(r"/(\d{8,})", frame_url)
            if place_match:
                place_id = place_match.group(1)
        except Exception:
            pass

        # 링크 추출 (블로그, 홈페이지 등)
        from scraper.blog import extract_links_from_detail
        links = await extract_links_from_detail(entry_frame)
        blog_url = links.get("blog_url")
        homepage_url = links.get("homepage_url")

        # 블로그 URL에서 네이버ID 추출
        if blog_url and not naver_id:
            id_match = re.match(r"https?://blog\.naver\.com/([a-zA-Z0-9_-]+)", blog_url)
            excluded = {'PostView', 'PostList', 'prologue', 'place', 'home'}
            if id_match and id_match.group(1) not in excluded:
                naver_id = id_match.group(1)

        # 심층 탐색: 홈페이지/블로그/인스타에서 gmail 등 실제 이메일 먼저 찾기
        if not email and context:
            try:
                from scraper.email_finder import find_email_enhanced
                extra = await find_email_enhanced(
                    context, entry_frame, name, search_region or search_category
                )
            except ImportError:
                from scraper.blog import find_email_comprehensive
                extra = await find_email_comprehensive(
                    context, entry_frame, name
                )
            if extra["email"] and not email:
                email = extra["email"]
            if extra["personal_phone"]:
                personal_phone = extra["personal_phone"]
            if extra.get("naver_id") and not naver_id:
                naver_id = extra["naver_id"]
            if extra.get("blog_url") and not blog_url:
                blog_url = extra["blog_url"]
            if extra.get("homepage_url") and not homepage_url:
                homepage_url = extra["homepage_url"]

        # 마지막 수단: 심층 탐색으로도 못 찾으면 블로그ID로 @naver.com 생성
        if not email and naver_id and blog_url and naver_id in blog_url:
            email = f"{naver_id}@naver.com"
            logger.info(f"  [블로그ID→네이버메일] {email} (다른 이메일 못 찾음)")

        biz = Business(
            name=name,
            phone=detail.get("phone") or None,
            personal_phone=personal_phone,
            email=email,
            naver_id=naver_id,
            address=detail.get("address") or None,
            category=category,
            blog_url=blog_url,
            homepage_url=homepage_url,
            place_id=place_id,
        )

        logger.info(
            f"  업체: {name} | 전화: {biz.phone or '-'} | "
            f"이메일: {biz.email or '-'} | "
            f"네이버ID: {biz.naver_id or '-'} | 주소: {biz.address or '-'}"
        )
        return biz

    except Exception as e:
        logger.error(f"'{name}' 상세 정보 추출 중 오류: {e}")
        return Business(name=name, category=search_category)
