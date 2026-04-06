"""네이버 블로그/홈페이지에서 추가 연락처를 추출하는 모듈

업체 상세 페이지에서 발견된 블로그/홈페이지 URL을 방문하여
010 개인번호, 이메일 등 추가 연락처 정보를 수집한다.
"""

import asyncio
import logging
import re
from playwright.async_api import BrowserContext, Page, Frame

logger = logging.getLogger(__name__)

PHONE_010_PATTERN = re.compile(r"010[-.\s]?\d{4}[-.\s]?\d{4}")
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# 무시할 이메일 도메인 (시스템/플랫폼 이메일)
IGNORED_EMAIL_DOMAINS = {
    "naver.com", "navercorp.com", "example.com",
    "noreply.com", "no-reply.com", "test.com",
    "google.com", "apple.com", "microsoft.com",
    "naver.net", "naverlabs.com",
}

# 무시할 이메일 접두어 (고객센터/시스템 이메일)
IGNORED_EMAIL_PREFIXES = {
    "helpcustomer", "help", "support", "admin", "webmaster",
    "privacy", "noreply", "no-reply", "postmaster", "mailer-daemon",
    "info@naver", "cs@naver", "contact@naver",
}


def _clean_phones(phones: list[str]) -> list[str]:
    """중복 제거 및 정규화"""
    seen = set()
    result = []
    for p in phones:
        normalized = re.sub(r"[-.\s]", "-", p)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _clean_emails(emails: list[str]) -> list[str]:
    """중복 제거 및 업체 무관 이메일 필터링"""
    seen = set()
    result = []
    for e in emails:
        lower = e.lower()
        domain = lower.split("@")[1] if "@" in lower else ""
        prefix = lower.split("@")[0] if "@" in lower else ""

        # 도메인 필터
        if domain in IGNORED_EMAIL_DOMAINS:
            continue

        # 접두어 필터 (시스템/고객센터 이메일)
        if any(lower.startswith(p) for p in IGNORED_EMAIL_PREFIXES):
            continue

        # 너무 짧거나 긴 이메일 제외
        if len(prefix) < 2 or len(e) > 60:
            continue

        # 이미지 파일명 등 오탐 제외
        if any(ext in lower for ext in [".png", ".jpg", ".gif", ".svg", ".css", ".js"]):
            continue

        if lower not in seen:
            seen.add(lower)
            result.append(e)
    return result


async def _extract_from_text(text: str) -> dict:
    """텍스트에서 010 번호와 이메일을 추출한다."""
    phones = PHONE_010_PATTERN.findall(text)
    emails = EMAIL_PATTERN.findall(text)
    return {
        "phones": _clean_phones(phones),
        "emails": _clean_emails(emails),
    }


async def _extract_from_page_and_frames(page: Page) -> dict:
    """페이지 본문 + 모든 iframe에서 연락처를 추출한다."""
    all_phones = []
    all_emails = []

    # 메인 프레임
    try:
        main_text = await page.evaluate("() => document.body?.innerText || ''")
        result = await _extract_from_text(main_text)
        all_phones.extend(result["phones"])
        all_emails.extend(result["emails"])
    except Exception as e:
        logger.debug(f"메인 프레임 텍스트 추출 실패: {e}")

    # 모든 서브 프레임 (네이버 블로그는 iframe 내에 본문이 있음)
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            frame_text = await frame.evaluate("() => document.body?.innerText || ''")
            if len(frame_text) > 50:  # 의미있는 컨텐츠가 있는 프레임만
                result = await _extract_from_text(frame_text)
                all_phones.extend(result["phones"])
                all_emails.extend(result["emails"])
        except Exception:
            continue

    return {
        "phones": _clean_phones(all_phones),
        "emails": _clean_emails(all_emails),
    }


async def extract_links_from_detail(entry_frame: Frame) -> dict:
    """상세 페이지에서 블로그/홈페이지/SNS 링크를 추출한다.

    Returns:
        {
            "blog_url": str | None,   # 공식 블로그 URL
            "homepage_url": str | None,  # 홈페이지 URL
            "sns_urls": list[str],    # SNS 링크 목록
        }
    """
    links = await entry_frame.evaluate(r"""
        () => {
            const result = {blog_url: null, homepage_url: null, sns_urls: []};
            const bodyText = document.body?.innerText || '';
            const lines = bodyText.split('\n').map(l => l.trim()).filter(l => l);

            // "홈페이지" / "블로그" 라벨 다음 URL
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                const next = (i + 1 < lines.length) ? lines[i + 1] : '';

                if (line === '홈페이지' || line === '블로그') {
                    if (next.startsWith('http')) {
                        if (next.includes('blog.naver.com')) {
                            result.blog_url = next;
                        } else if (next.includes('instagram.com') || next.includes('facebook.com')) {
                            result.sns_urls.push(next);
                        } else {
                            result.homepage_url = next;
                        }
                    }
                }
            }

            // a 태그에서 블로그 링크 추가 탐색 (홈페이지 라벨에서 못 찾은 경우)
            if (!result.blog_url) {
                // 업체가 직접 등록한 블로그 링크 (class에 CHmqa 등)
                const blogLinks = document.querySelectorAll('a[href*="blog.naver.com"]');
                for (const a of blogLinks) {
                    const href = a.href;
                    // 블로그 메인 페이지 형태 (포스트 번호가 없는 것)
                    if (href.match(/blog\.naver\.com\/[^\/]+\/?$/)) {
                        result.blog_url = href;
                        break;
                    }
                }
            }

            return result;
        }
    """)

    return links


async def scrape_blog(
    context: BrowserContext,
    blog_url: str,
    timeout_ms: int = 15000,
) -> dict:
    """네이버 블로그를 방문하여 010 번호와 이메일을 추출한다.

    Args:
        context: Playwright 브라우저 컨텍스트
        blog_url: 블로그 URL

    Returns:
        {"phones": [str], "emails": [str]}
    """
    # 블로그 URL에서 블로그 ID 추출하여 메인 페이지로 이동
    blog_main_url = blog_url
    # 개별 포스트 URL이면 블로그 메인으로 변환
    match = re.match(r"(https?://blog\.naver\.com/[^/]+)", blog_url)
    if match:
        blog_main_url = match.group(1)

    logger.info(f"  블로그 방문: {blog_main_url}")

    page = await context.new_page()
    all_phones = []
    all_emails = []

    try:
        # 1단계: 블로그 메인 페이지 방문
        await page.goto(blog_main_url, wait_until="networkidle", timeout=timeout_ms)
        await asyncio.sleep(1.5)

        result = await _extract_from_page_and_frames(page)
        all_phones.extend(result["phones"])
        all_emails.extend(result["emails"])

        # 2단계: 프로필/소개 페이지 확인
        blog_id_match = re.match(r"https?://blog\.naver\.com/([^/?]+)", blog_main_url)
        if blog_id_match:
            blog_id = blog_id_match.group(1)
            profile_url = f"https://blog.naver.com/ProfileDisplay.naver?blogId={blog_id}"

            try:
                await page.goto(profile_url, wait_until="networkidle", timeout=timeout_ms)
                await asyncio.sleep(1)

                profile_result = await _extract_from_page_and_frames(page)
                all_phones.extend(profile_result["phones"])
                all_emails.extend(profile_result["emails"])
            except Exception as e:
                logger.debug(f"  프로필 페이지 접근 실패: {e}")

        # 3단계: 최근 글에서 연락처 탐색 (아직 못 찾은 경우)
        if not all_phones and not all_emails and blog_id_match:
            blog_id = blog_id_match.group(1)
            try:
                # 블로그 메인으로 돌아가서 최근 글 링크 수집
                await page.goto(blog_main_url, wait_until="networkidle", timeout=timeout_ms)
                await asyncio.sleep(1)

                # 모든 프레임에서 포스트 링크 수집
                post_urls = set()
                for frame in page.frames:
                    try:
                        urls = await frame.evaluate("""
                            () => {
                                const links = [];
                                document.querySelectorAll('a[href]').forEach(a => {
                                    const href = a.href || '';
                                    if (href.includes('/PostView') || href.match(/blog\\.naver\\.com\\/[^/]+\\/\\d+/)) {
                                        links.push(href);
                                    }
                                });
                                return [...new Set(links)].slice(0, 5);
                            }
                        """)
                        for u in urls:
                            post_urls.add(u)
                    except Exception:
                        continue

                # 최근 글 2개만 방문
                for post_url in list(post_urls)[:2]:
                    try:
                        logger.debug(f"  블로그 글 확인: {post_url[:80]}")
                        await page.goto(post_url, wait_until="networkidle", timeout=timeout_ms)
                        await asyncio.sleep(1)

                        post_result = await _extract_from_page_and_frames(page)
                        all_phones.extend(post_result["phones"])
                        all_emails.extend(post_result["emails"])

                        if all_phones or all_emails:
                            break  # 찾으면 중단
                    except Exception:
                        continue

            except Exception as e:
                logger.debug(f"  최근 글 탐색 실패: {e}")

    except Exception as e:
        logger.debug(f"  블로그 접근 실패: {e}")
    finally:
        await page.close()

    final = {
        "phones": _clean_phones(all_phones),
        "emails": _clean_emails(all_emails),
    }

    if final["phones"] or final["emails"]:
        logger.info(
            f"  블로그에서 발견 - 010: {final['phones']}, "
            f"이메일: {final['emails']}"
        )
    else:
        logger.debug("  블로그에서 추가 연락처 없음")

    return final


async def scrape_homepage(
    context: BrowserContext,
    homepage_url: str,
    timeout_ms: int = 15000,
) -> dict:
    """일반 홈페이지를 방문하여 010 번호와 이메일을 추출한다."""
    logger.info(f"  홈페이지 방문: {homepage_url}")

    page = await context.new_page()

    try:
        await page.goto(homepage_url, wait_until="networkidle", timeout=timeout_ms)
        await asyncio.sleep(1)

        result = await _extract_from_page_and_frames(page)

        if result["phones"] or result["emails"]:
            logger.info(
                f"  홈페이지에서 발견 - 010: {result['phones']}, "
                f"이메일: {result['emails']}"
            )
        else:
            logger.debug("  홈페이지에서 추가 연락처 없음")

        return result

    except Exception as e:
        logger.debug(f"  홈페이지 접근 실패: {e}")
        return {"phones": [], "emails": []}
    finally:
        await page.close()


async def scrape_smartstore(
    context: BrowserContext,
    store_url: str,
    timeout_ms: int = 15000,
) -> dict:
    """네이버 스마트스토어 판매자 정보에서 이메일을 추출한다.

    스마트스토어 /profile 페이지에는 사업자 이메일이 법적 필수 표기되어 있다.
    """
    # 스토어 메인 URL에서 /profile 경로 생성
    if not store_url.rstrip("/").endswith("/profile"):
        profile_url = store_url.rstrip("/") + "/profile"
    else:
        profile_url = store_url

    logger.info(f"  스마트스토어 방문: {profile_url}")

    page = await context.new_page()

    try:
        await page.goto(profile_url, wait_until="networkidle", timeout=timeout_ms)
        await asyncio.sleep(1)

        text = await page.evaluate("() => document.body?.innerText || ''")
        emails = EMAIL_PATTERN.findall(text)
        emails = _clean_emails(emails)

        phones = PHONE_010_PATTERN.findall(text)
        phones = _clean_phones(phones)

        if emails:
            logger.info(f"  스마트스토어에서 이메일 발견: {emails}")
        else:
            logger.debug("  스마트스토어에서 이메일 없음")

        return {"phones": phones, "emails": emails}

    except Exception as e:
        logger.debug(f"  스마트스토어 접근 실패: {e}")
        return {"phones": [], "emails": []}
    finally:
        await page.close()


async def find_email_comprehensive(
    context: BrowserContext,
    entry_frame,
    name: str,
) -> dict:
    """다방면으로 이메일을 찾는 통합 함수.

    탐색 순서 (신뢰도 높은 순):
    1. 플레이스 상세 페이지 (이미 추출된 경우 스킵)
    2. 업체 홈페이지 방문
    3. 공식 블로그 프로필/본문
    4. 네이버 스마트스토어 판매자 정보

    Returns:
        {"email": str|None, "personal_phone": str|None,
         "blog_url": str|None, "homepage_url": str|None}
    """
    email = None
    personal_phone = None
    blog_url = None
    homepage_url = None

    # 링크 추출
    links = await extract_links_from_detail(entry_frame)
    blog_url = links.get("blog_url")
    homepage_url = links.get("homepage_url")

    # 스마트스토어 링크도 추출
    smartstore_url = await entry_frame.evaluate(r"""
        () => {
            const links = document.querySelectorAll('a[href]');
            for (const a of links) {
                const href = a.href || '';
                if (href.includes('smartstore.naver.com') && !href.includes('inflow')) {
                    return href;
                }
            }
            // 텍스트에서 스마트스토어 URL 패턴 찾기
            const text = document.body?.innerText || '';
            const match = text.match(/smartstore\.naver\.com\/[a-zA-Z0-9_-]+/);
            if (match) return 'https://' + match[0];
            return null;
        }
    """)

    # 1. 홈페이지 방문
    if homepage_url:
        try:
            hp_result = await scrape_homepage(context, homepage_url)
            if hp_result["emails"]:
                email = hp_result["emails"][0]
            if hp_result["phones"]:
                personal_phone = hp_result["phones"][0]
        except Exception:
            pass

    # 2. 블로그 방문 (이메일 아직 없으면)
    if blog_url and not email:
        try:
            blog_result = await scrape_blog(context, blog_url)
            if blog_result["emails"] and not email:
                email = blog_result["emails"][0]
            if blog_result["phones"] and not personal_phone:
                personal_phone = blog_result["phones"][0]
        except Exception:
            pass

    # 3. 스마트스토어 (이메일 아직 없으면)
    if smartstore_url and not email:
        try:
            store_result = await scrape_smartstore(context, smartstore_url)
            if store_result["emails"]:
                email = store_result["emails"][0]
        except Exception:
            pass

    # 블로그 URL에서 네이버 아이디 추출
    naver_id = None
    if blog_url:
        id_match = re.match(r"https?://blog\.naver\.com/([^/?]+)", blog_url)
        if id_match:
            naver_id = id_match.group(1)

    return {
        "email": email,
        "personal_phone": personal_phone,
        "naver_id": naver_id,
        "blog_url": blog_url,
        "homepage_url": homepage_url,
    }
