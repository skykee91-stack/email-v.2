"""이메일 추출 강화 모듈

기존 방법(플레이스 상세, 블로그, 홈페이지, 스마트스토어)에 추가로:
1. 홈페이지 하위 페이지 (회사소개, 연락처, 문의 등) 탐색
2. 네이버 검색으로 이메일 직접 검색
3. 인스타그램 프로필 이메일 추출
4. mailto: 링크 추출
5. 구조화 데이터 (JSON-LD, meta 태그) 추출

목표: 100개 업체 중 60개 이상 이메일 확보
"""

import asyncio
import logging
import re
from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

IGNORED_DOMAINS = {
    "naver.com", "navercorp.com", "example.com", "noreply.com",
    "google.com", "apple.com", "microsoft.com", "naver.net",
    "sentry.io", "wixpress.com", "w3.org", "schema.org",
    "ogp.me", "purl.org", "xmlns.com", "github.com",
    "googleapis.com", "gstatic.com", "jquery.com",
    "jsdelivr.net", "cloudflare.com", "fontawesome.com",
}

IGNORED_PREFIXES = {
    "help", "support", "admin", "webmaster", "privacy",
    "noreply", "no-reply", "postmaster", "mailer-daemon",
    "info@naver", "cs@naver", "contact@naver", "service",
}


def clean_email(email: str) -> str | None:
    """이메일 유효성 검사 및 정리"""
    email = email.lower().strip()
    domain = email.split("@")[1] if "@" in email else ""
    prefix = email.split("@")[0] if "@" in email else ""

    if domain in IGNORED_DOMAINS:
        return None
    if any(email.startswith(p) for p in IGNORED_PREFIXES):
        return None
    if len(prefix) < 2 or len(email) > 60:
        return None
    if any(ext in email for ext in [".png", ".jpg", ".gif", ".svg", ".css", ".js", ".php"]):
        return None
    # 숫자만으로 된 prefix 제외 (보통 오탐)
    if prefix.isdigit():
        return None

    return email


def extract_emails_from_text(text: str) -> list[str]:
    """텍스트에서 이메일 추출 + 필터링"""
    raw = EMAIL_PATTERN.findall(text)
    result = []
    seen = set()
    for e in raw:
        cleaned = clean_email(e)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


async def extract_from_page_comprehensive(page: Page) -> list[str]:
    """페이지에서 다양한 방법으로 이메일 추출"""
    all_emails = []

    try:
        # 1. 페이지 텍스트에서 추출
        text = await page.evaluate("() => document.body?.innerText || ''")
        all_emails.extend(extract_emails_from_text(text))

        # 2. mailto: 링크에서 추출 (가장 신뢰도 높음)
        mailto_emails = await page.evaluate("""
            () => {
                const emails = [];
                document.querySelectorAll('a[href^="mailto:"]').forEach(a => {
                    const href = a.href.replace('mailto:', '').split('?')[0].trim();
                    if (href.includes('@')) emails.push(href);
                });
                return emails;
            }
        """)
        all_emails.extend([e for e in mailto_emails if clean_email(e)])

        # 3. meta 태그에서 추출
        meta_emails = await page.evaluate("""
            () => {
                const emails = [];
                document.querySelectorAll('meta').forEach(m => {
                    const content = m.getAttribute('content') || '';
                    const match = content.match(/[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/);
                    if (match) emails.push(match[0]);
                });
                return emails;
            }
        """)
        all_emails.extend([e for e in meta_emails if clean_email(e)])

        # 4. JSON-LD 구조화 데이터에서 추출
        jsonld_emails = await page.evaluate("""
            () => {
                const emails = [];
                document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                    try {
                        const data = JSON.parse(s.textContent);
                        const findEmail = (obj) => {
                            if (!obj || typeof obj !== 'object') return;
                            if (obj.email) emails.push(obj.email);
                            if (obj.contactPoint?.email) emails.push(obj.contactPoint.email);
                            if (Array.isArray(obj.contactPoint)) {
                                obj.contactPoint.forEach(c => { if (c.email) emails.push(c.email); });
                            }
                            Object.values(obj).forEach(v => {
                                if (typeof v === 'object') findEmail(v);
                            });
                        };
                        findEmail(data);
                    } catch {}
                });
                return emails;
            }
        """)
        all_emails.extend([e for e in jsonld_emails if clean_email(e)])

        # 5. 모든 iframe 내부도 확인
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_text = await frame.evaluate("() => document.body?.innerText || ''")
                if len(frame_text) > 30:
                    all_emails.extend(extract_emails_from_text(frame_text))
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"페이지 이메일 추출 오류: {e}")

    # 중복 제거
    seen = set()
    result = []
    for e in all_emails:
        cleaned = clean_email(e)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


async def crawl_homepage_deep(
    context: BrowserContext,
    homepage_url: str,
    timeout_ms: int = 8000,
) -> list[str]:
    """홈페이지 + 하위 페이지(회사소개, 연락처 등)에서 이메일 추출

    일반적으로 이메일은 메인이 아닌 하위 페이지에 있는 경우가 많음
    """
    all_emails = []
    page = await context.new_page()

    try:
        # 1. 메인 페이지
        await page.goto(homepage_url, wait_until="networkidle", timeout=timeout_ms)
        await asyncio.sleep(1)
        main_emails = await extract_from_page_comprehensive(page)
        all_emails.extend(main_emails)

        if all_emails:
            return all_emails  # 메인에서 찾으면 바로 반환

        # 2. 하위 페이지 링크 수집
        sub_pages = await page.evaluate("""
            (baseUrl) => {
                const links = [];
                const keywords = [
                    'contact', 'about', 'company', 'info', 'inquiry',
                    '회사소개', '연락처', '문의', '오시는', '회사정보',
                    '상담', '견적', 'support', 'help'
                ];
                const seen = new Set();

                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.href;
                    const text = (a.textContent || '').toLowerCase().trim();
                    const hrefLower = href.toLowerCase();

                    // 같은 도메인만
                    try {
                        const linkDomain = new URL(href).hostname;
                        const baseDomain = new URL(baseUrl).hostname;
                        if (linkDomain !== baseDomain) return;
                    } catch { return; }

                    // 키워드 매칭
                    const matches = keywords.some(k =>
                        hrefLower.includes(k) || text.includes(k)
                    );

                    if (matches && !seen.has(href) && href !== baseUrl) {
                        seen.add(href);
                        links.push(href);
                    }
                });

                // 푸터 영역의 링크도 추가
                const footer = document.querySelector('footer') || document.querySelector('[class*="footer"]');
                if (footer) {
                    footer.querySelectorAll('a[href]').forEach(a => {
                        const href = a.href;
                        if (!seen.has(href) && href.startsWith('http')) {
                            seen.add(href);
                            links.push(href);
                        }
                    });
                }

                return links.slice(0, 5);
            }
        """, homepage_url)

        # 3. 하위 페이지 방문
        for sub_url in sub_pages[:3]:  # 최대 3개만
            try:
                await page.goto(sub_url, wait_until="networkidle", timeout=timeout_ms)
                await asyncio.sleep(1.5)
                sub_emails = await extract_from_page_comprehensive(page)
                all_emails.extend(sub_emails)
                if all_emails:
                    break
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"홈페이지 심층 크롤링 실패: {e}")
    finally:
        await page.close()

    # 중복 제거
    seen = set()
    return [e for e in all_emails if e not in seen and not seen.add(e)]


async def search_naver_for_email(
    context: BrowserContext,
    business_name: str,
    region: str = "",
    timeout_ms: int = 5000,
) -> list[str]:
    """네이버 검색으로 업체 이메일 찾기

    "{업체명} {지역} 이메일" 등으로 검색하여 이메일 추출
    """
    from urllib.parse import quote

    queries = [
        f"{business_name} 이메일",
        f"{business_name} email",
    ]

    all_emails = []
    page = await context.new_page()

    try:
        for query in queries:
            if all_emails:
                break
            try:
                # 네이버 검색
                url = f"https://search.naver.com/search.naver?query={quote(query)}"
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                await asyncio.sleep(1)

                text = await page.evaluate("() => document.body?.innerText || ''")
                emails = extract_emails_from_text(text)
                all_emails.extend(emails)
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"검색 이메일 탐색 실패: {e}")
    finally:
        await page.close()

    return all_emails


async def extract_instagram_email(
    context: BrowserContext,
    instagram_url: str,
    timeout_ms: int = 8000,
) -> list[str]:
    """인스타그램 프로필에서 이메일 추출

    인스타그램 프로필 bio에 이메일을 올리는 업체가 많음.
    또한 mailto: 링크, JSON-LD 구조화 데이터에도 이메일이 있을 수 있음.
    """
    page = await context.new_page()
    try:
        await page.goto(instagram_url, wait_until="networkidle", timeout=timeout_ms)
        await asyncio.sleep(1.5)

        # 1. 페이지 텍스트에서 추출
        text = await page.evaluate("() => document.body?.innerText || ''")
        emails = extract_emails_from_text(text)
        if emails:
            return emails

        # 2. mailto: 링크
        mailto = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href^="mailto:"]');
                const emails = [];
                for (const a of links) {
                    const href = (a.href || '').replace('mailto:', '').split('?')[0].trim();
                    if (href.includes('@')) emails.push(href);
                }
                return emails;
            }
        """)
        if mailto:
            return [e for e in mailto if clean_email(e)]

        # 3. meta 태그
        meta_emails = await page.evaluate("""
            () => {
                const emails = [];
                document.querySelectorAll('meta[content]').forEach(m => {
                    const c = m.getAttribute('content') || '';
                    const match = c.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                    if (match) emails.push(match[0]);
                });
                return emails;
            }
        """)
        if meta_emails:
            return [e for e in meta_emails if clean_email(e)]

        return []
    except Exception:
        return []
    finally:
        await page.close()


async def find_email_enhanced(
    context: BrowserContext,
    entry_frame,
    name: str,
    region: str = "",
) -> dict:
    """강화된 이메일 탐색 - 기존 방법 + 신규 방법 결합

    탐색 순서 (신뢰도 높은 순):
    1. 플레이스 상세 페이지 (기존)
    2. 스마트스토어 /profile (법적 필수 표기 → 신뢰도 최고)
    3. 업체 홈페이지 심층 크롤링 (메인 + 하위 페이지)
    4. 블로그 프로필/본문 (기존 강화)
    5. 인스타그램 프로필
    6. 네이버 검색
    """
    from scraper.blog import (
        extract_links_from_detail,
        scrape_blog,
        scrape_smartstore,
    )

    email = None
    personal_phone = None
    blog_url = None
    homepage_url = None
    naver_id = None

    # 모든 외부 링크 한번에 추출
    all_links = await entry_frame.evaluate(r"""
        () => {
            const result = {
                blog_url: null, homepage_url: null, smartstore_url: null,
                instagram_url: null, sns_urls: [], booking_url: null
            };
            const anchors = document.querySelectorAll('a[href]');
            for (const a of anchors) {
                const href = a.href || '';
                if (href.includes('blog.naver.com')) {
                    const m = href.match(/blog\.naver\.com\/[a-zA-Z0-9_-]+\/?$/);
                    if (m) result.blog_url = href;
                } else if (href.includes('smartstore.naver.com') && !href.includes('inflow')) {
                    result.smartstore_url = href;
                } else if (href.includes('instagram.com')) {
                    result.instagram_url = href;
                    result.sns_urls.push(href);
                } else if (href.includes('facebook.com')) {
                    result.sns_urls.push(href);
                } else if (href.includes('booking.naver.com') || href.includes('m.booking.naver.com')) {
                    result.booking_url = href;
                } else if (href.startsWith('http') && !href.includes('naver.com')
                    && !href.includes('naver.net') && !href.includes('policy.naver')
                    && !href.includes('help.naver')) {
                    if (!result.homepage_url) result.homepage_url = href;
                }
            }

            // 텍스트에서도 추출
            const bodyText = document.body?.innerText || '';
            const lines = bodyText.split('\n').map(l => l.trim());
            for (let i = 0; i < lines.length; i++) {
                if ((lines[i] === '홈페이지' || lines[i] === '블로그') && i+1 < lines.length) {
                    const next = lines[i+1];
                    if (next.includes('blog.naver.com') && !result.blog_url) {
                        result.blog_url = next;
                    } else if (next.includes('instagram.com')) {
                        result.instagram_url = next;
                    } else if (next.startsWith('http') && !next.includes('naver.com') && !result.homepage_url) {
                        result.homepage_url = next;
                    }
                }
            }

            return result;
        }
    """)

    blog_url = all_links.get("blog_url")
    homepage_url = all_links.get("homepage_url")
    smartstore_url = all_links.get("smartstore_url")
    instagram_url = all_links.get("instagram_url")
    sns_urls = all_links.get("sns_urls", [])
    booking_url = all_links.get("booking_url")

    # 010 번호 추출 (상세 페이지에서)
    try:
        detail_text = await entry_frame.evaluate("() => document.body?.innerText || ''")
        import re
        phone_match = re.search(r"010[-.\s]?\d{4}[-.\s]?\d{4}", detail_text)
        if phone_match:
            personal_phone = re.sub(r"[-.\s]", "-", phone_match.group())
    except Exception:
        pass

    # 0. 플레이스 "정보" 탭 직접 방문 (숨겨진 이메일/연락처 있을 수 있음)
    if not email:
        try:
            frame_url = entry_frame.url
            info_url = re.sub(r"/home(\?|$)", r"/information\1", frame_url)
            if "/information" not in frame_url and info_url != frame_url:
                info_page = await context.new_page()
                try:
                    await info_page.goto(info_url, wait_until="networkidle", timeout=6000)
                    await asyncio.sleep(1)
                    info_text = await info_page.evaluate("() => document.body?.innerText || ''")
                    info_emails = extract_emails_from_text(info_text)
                    if info_emails:
                        email = info_emails[0]
                        logger.info(f"  [정보탭] 이메일 발견: {email}")

                    # 정보탭에서 추가 링크도 추출
                    if not homepage_url:
                        hp = await info_page.evaluate(r"""
                            () => {
                                const links = document.querySelectorAll('a[href]');
                                for (const a of links) {
                                    const h = a.href || '';
                                    if (h.startsWith('http') && !h.includes('naver.com')
                                        && !h.includes('naver.net')) return h;
                                }
                                return null;
                            }
                        """)
                        if hp:
                            homepage_url = hp
                    if not instagram_url:
                        ig = await info_page.evaluate(r"""
                            () => {
                                const links = document.querySelectorAll('a[href*="instagram.com"]');
                                return links.length > 0 ? links[0].href : null;
                            }
                        """)
                        if ig:
                            instagram_url = ig
                finally:
                    await info_page.close()
        except Exception as e:
            logger.debug(f"정보탭 방문 실패: {e}")

    # 1. 스마트스토어 (신뢰도 최고 - 법적 필수 표기)
    if smartstore_url and not email:
        try:
            store_result = await scrape_smartstore(context, smartstore_url)
            if store_result["emails"]:
                email = store_result["emails"][0]
                logger.info(f"  [스마트스토어] 이메일 발견: {email}")
        except Exception:
            pass

    # 2. 홈페이지 심층 크롤링
    if homepage_url and not email:
        try:
            hp_emails = await crawl_homepage_deep(context, homepage_url)
            if hp_emails:
                email = hp_emails[0]
                logger.info(f"  [홈페이지] 이메일 발견: {email}")
        except Exception:
            pass

    # 3. 블로그 (프로필 + 최근 글)
    if blog_url and not email:
        try:
            blog_result = await scrape_blog(context, blog_url)
            if blog_result["emails"]:
                email = blog_result["emails"][0]
                logger.info(f"  [블로그] 이메일 발견: {email}")
            if blog_result["phones"] and not personal_phone:
                personal_phone = blog_result["phones"][0]
        except Exception:
            pass

    # 4. 인스타그램 / 네이버 검색 — 비활성화 (속도 대비 효과 낮음)
    # gmail은 홈페이지/블로그/스마트스토어에서 충분히 확보 가능

    # 네이버 아이디 추출 (여러 소스)
    # 1. 블로그 URL
    if blog_url and not naver_id:
        id_match = re.match(r"https?://blog\.naver\.com/([a-zA-Z0-9_-]+)", blog_url)
        if id_match and id_match.group(1) not in ("PostView", "PostList", "prologue"):
            naver_id = id_match.group(1)

    # 2. 스마트스토어 URL
    if smartstore_url and not naver_id:
        store_match = re.search(r"smartstore\.naver\.com/([a-zA-Z0-9_-]+)", smartstore_url)
        if store_match and store_match.group(1) != "main":
            naver_id = store_match.group(1)

    return {
        "email": email,
        "personal_phone": personal_phone,
        "naver_id": naver_id,
        "blog_url": blog_url,
        "homepage_url": homepage_url,
    }
