"""PyInstaller 빌드 스크립트

사용법: python build.py
       python build.py --console    (디버그용 콘솔 모드)
결과: dist/N플레이스업체추출기/ 폴더에 exe 및 필요 파일 생성
"""

import PyInstaller.__main__
import os
import sys
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_PACKAGES = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages")

playwright_dir = os.path.join(SITE_PACKAGES, "playwright", "driver")
customtkinter_dir = os.path.join(SITE_PACKAGES, "customtkinter")

# 콘솔 모드 여부 (디버그용)
console_mode = "--console" in sys.argv

print(f"Building from: {BASE_DIR}")
print(f"Mode: {'CONSOLE (디버그)' if console_mode else 'WINDOWED (배포)'}")

args = [
    os.path.join(BASE_DIR, "app.py"),
    "--name=N플레이스업체추출기",
    "--console" if console_mode else "--windowed",
    "--noconfirm",
    # 아이콘
    f"--icon={os.path.join(BASE_DIR, 'icon.ico')}",
    # ─── Python 모듈 검색 경로 ───
    f"--paths={BASE_DIR}",
    # ─── 데이터 파일 (코드가 아닌 리소스) ───
    # Playwright 드라이버
    f"--add-data={playwright_dir};playwright/driver",
    # CustomTkinter (테마/JSON 파일)
    f"--add-data={customtkinter_dir};customtkinter",
    # 로고/아이콘
    f"--add-data={os.path.join(BASE_DIR, 'logo.png')};.",
    f"--add-data={os.path.join(BASE_DIR, 'icon.ico')};.",
    # ─── 숨겨진 import (PyInstaller가 자동 감지 못하는 모듈) ───
    "--hidden-import=config",
    "--hidden-import=data",
    "--hidden-import=models",
    "--hidden-import=models.business",
    "--hidden-import=scraper",
    "--hidden-import=scraper.browser",
    "--hidden-import=scraper.search",
    "--hidden-import=scraper.detail",
    "--hidden-import=scraper.blog",
    "--hidden-import=scraper.blog_search",
    "--hidden-import=export",
    "--hidden-import=export.excel",
    "--hidden-import=playwright",
    "--hidden-import=playwright.async_api",
    "--hidden-import=playwright._impl",
    "--hidden-import=playwright._impl._api_types",
    "--hidden-import=pydantic",
    "--hidden-import=openpyxl",
    "--hidden-import=click",
    "--hidden-import=greenlet",
    "--hidden-import=customtkinter",
    "--hidden-import=darkdetect",
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    # ─── 전체 수집 (playwright 관련 바이너리 포함) ───
    "--collect-all=playwright",
    # ─── 경로 ───
    "--distpath", os.path.join(BASE_DIR, "dist"),
    "--workpath", os.path.join(BASE_DIR, "build"),
    "--specpath", BASE_DIR,
]

PyInstaller.__main__.run(args)

# Playwright 브라우저를 dist에 복사
dist_dir = os.path.join(BASE_DIR, "dist", "N플레이스업체추출기")
pw_default = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")
pw_project = os.path.join(BASE_DIR, "browsers")
pw_source = pw_project if os.path.exists(pw_project) else pw_default

if os.path.exists(pw_source):
    dest_browsers = os.path.join(dist_dir, "browsers")
    if os.path.exists(dest_browsers):
        shutil.rmtree(dest_browsers)
    # chromium만 복사 (용량 절약)
    os.makedirs(dest_browsers, exist_ok=True)
    for item in os.listdir(pw_source):
        src = os.path.join(pw_source, item)
        if item.startswith("chromium") or item == ".links":
            dst = os.path.join(dest_browsers, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    print(f"Playwright browsers 복사 완료: {pw_source} → {dest_browsers}")
else:
    print(f"WARNING: Playwright browsers를 찾을 수 없습니다: {pw_source}")
    print("  먼저 'playwright install chromium'을 실행하세요")

# 빌드 임시 파일 정리
build_dir = os.path.join(BASE_DIR, "build")
if os.path.exists(build_dir):
    shutil.rmtree(build_dir)
for f in os.listdir(BASE_DIR):
    if f.endswith(".spec"):
        os.remove(os.path.join(BASE_DIR, f))

print(f"\n빌드 완료! ({'콘솔' if console_mode else '배포'} 모드)")
print(f"실행 파일: dist/N플레이스업체추출기/N플레이스업체추출기.exe")
