"""Playwright 브라우저 관리 모듈 (프록시 + 스텔스 지원)"""

import asyncio
import os
import random
import subprocess
import socket
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

# User-Agent 랜덤 목록 (한국 브라우저처럼 보이게)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]


@asynccontextmanager
async def create_browser(headed: bool = False, use_proxy: bool = False):
    """Playwright 브라우저 컨텍스트를 생성하고 관리한다.

    Args:
        headed: True면 브라우저 화면을 표시 (디버깅용)
        use_proxy: True면 프록시 사용 (기본값: False = 직접 연결)
                   직접 연결로 시작하고, 차단 시에만 프록시 사용 권장

    Yields:
        (browser, context, page) 튜플
    """
    # 프록시 설정 (환경변수 또는 기본값)
    proxy_config = None
    proxy_host = os.environ.get('PROXY_HOST', 'geo.iproyal.com')
    proxy_port = os.environ.get('PROXY_PORT', '12321')
    proxy_user = os.environ.get('PROXY_USER', '')
    proxy_pass = os.environ.get('PROXY_PASS', '')

    if use_proxy and proxy_host:
        proxy_config = {
            "server": f"http://{proxy_host}:{proxy_port}",
        }
        # Whitelist 방식이 아닌 경우 인증 추가
        if proxy_user and proxy_pass:
            proxy_config["username"] = proxy_user
            proxy_config["password"] = f"{proxy_pass}_country-kr"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not headed,
            proxy=proxy_config if proxy_config else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            user_agent=random.choice(USER_AGENTS),
        )
        page = await context.new_page()

        # 불필요한 리소스 차단 (트래픽 절감)
        # 주의: CSS는 차단하면 안 됨 (네이버 지도 iframe 로드에 필요)
        await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico,woff,woff2,ttf,eot,mp4,webm,ogg}", lambda route: route.abort())
        await page.route("**/static/image/**", lambda route: route.abort())
        await page.route("**/static/font/**", lambda route: route.abort())
        await page.route("**/analytics/**", lambda route: route.abort())
        await page.route("**/ads/**", lambda route: route.abort())

        # 스텔스 모드 적용 (봇 탐지 우회)
        if HAS_STEALTH:
            await stealth_async(page)

        try:
            yield browser, context, page
        finally:
            await context.close()
            await browser.close()
