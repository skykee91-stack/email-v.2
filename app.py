"""N플레이스 업체 추출기 - GUI 애플리케이션 (CustomTkinter)"""

import asyncio
import json
import logging
import os
import random
import sys
import threading
import queue
import traceback
from datetime import datetime
from tkinter import filedialog, END

# ─── 경로 설정 (PyInstaller frozen exe 대응) ───
if getattr(sys, 'frozen', False):
    # PyInstaller exe: 실행파일 경로
    EXE_DIR = os.path.dirname(sys.executable)
    # _internal 폴더 (번들된 모듈/데이터가 여기에 있음)
    INTERNAL_DIR = os.path.join(EXE_DIR, "_internal")
    if os.path.isdir(INTERNAL_DIR):
        BASE_DIR = INTERNAL_DIR
    else:
        BASE_DIR = EXE_DIR
    # 모듈 검색 경로에 _internal 추가
    for p in [INTERNAL_DIR, EXE_DIR]:
        if p not in sys.path:
            sys.path.insert(0, p)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = EXE_DIR

os.chdir(EXE_DIR)

import customtkinter as ctk

from config import DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, MAX_RESULTS
from models.business import Business
from scraper.browser import create_browser
from export.excel import export_to_excel
from data import REGIONS, CATEGORIES, KEYWORD_GROUPS


def ensure_browser_installed():
    """Playwright Chromium 브라우저 설치 확인"""
    browsers_path = os.path.join(EXE_DIR, "browsers")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

    if os.path.exists(browsers_path) and any(
        d.startswith("chromium") for d in os.listdir(browsers_path)
        if os.path.isdir(os.path.join(browsers_path, d))
    ):
        return True

    try:
        import subprocess

        if getattr(sys, 'frozen', False):
            # frozen exe: playwright 모듈을 직접 호출
            python_cmd = [sys.executable]
            # _internal에 playwright CLI가 있는지 확인
            pw_cli = os.path.join(BASE_DIR, "playwright", "driver", "package", "cli.js")
            node_exe = os.path.join(BASE_DIR, "playwright", "driver", "node.exe")
            if os.path.exists(pw_cli) and os.path.exists(node_exe):
                result = subprocess.run(
                    [node_exe, pw_cli, "install", "chromium"],
                    capture_output=True, timeout=300,
                    env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": browsers_path},
                )
                return result.returncode == 0
            else:
                # fallback: pip로 설치된 playwright에서 찾기
                from playwright.__main__ import main as pw_main
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
                sys.argv = ["playwright", "install", "chromium"]
                try:
                    pw_main()
                    return True
                except SystemExit:
                    return True  # playwright install이 sys.exit(0)으로 끝남
        else:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, timeout=300,
                env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": browsers_path},
            )
            return result.returncode == 0
    except Exception as e:
        logging.error(f"브라우저 설치 실패: {e}")
        return False


# ─── 로깅 핸들러 ───
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_queue.put(msg)
        except Exception:
            pass


# ─── 수집 히스토리 (이전 수집 업체 중복 방지) ───
HISTORY_FILE = os.path.join(EXE_DIR, "collected_history.json")


def load_history():
    """이전에 수집했던 업체의 place_id/dedup_key 목록을 불러옴"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("collected_ids", []))
        except Exception:
            return set()
    return set()


def save_history(collected_ids):
    """수집한 업체의 place_id/dedup_key 목록을 저장"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"collected_ids": list(collected_ids)}, f, ensure_ascii=False)
    except Exception as e:
        logging.error(f"히스토리 저장 실패: {e}")


# ─── 크롤링 워커 ───
class CrawlWorker:
    def __init__(self, log_queue, progress_queue):
        self.log_queue = log_queue
        self.progress_queue = progress_queue
        self.businesses = []
        self.is_running = False
        self.should_stop = False
        self.history_ids = set()  # 이전 수집 업체 ID

    def _log(self, msg):
        self.log_queue.put(msg)

    def _progress(self, current, total, status=""):
        self.progress_queue.put((current, total, status))

    def run_place_mode(self, region, category, max_results, deep_search, delay_min, delay_max, keywords=None):
        self.is_running = True
        self.should_stop = False
        self.businesses = []
        self.history_ids = load_history()
        asyncio.run(self._place_mode(region, category, max_results, deep_search, delay_min, delay_max, keywords))
        save_history(self.history_ids)
        self.is_running = False

    async def _place_mode(self, region, category, max_results, deep_search, delay_min, delay_max, keywords=None):
        from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
        from scraper.detail import click_and_extract
        from config import LONG_PAUSE_INTERVAL, LONG_PAUSE_MIN, LONG_PAUSE_MAX

        search_keywords = keywords if keywords and len(keywords) > 0 else [category]
        scan_per_keyword = max(50, (max_results * 3) // len(search_keywords))
        seen_ids = set(self.history_ids)  # 이전 수집 히스토리 포함
        collected = 0
        history_count = len(self.history_ids)
        if history_count > 0:
            self._log(f"기존 수집 히스토리: {history_count}개 업체 (자동 중복 제거)")

        async with create_browser(headed=False) as (browser, context, page):
            try:
                self._log(f"목표: 업체 {max_results}개 수집")
                self._log(f"검색 키워드: {', '.join(search_keywords)}")

                for kw_idx, keyword in enumerate(search_keywords):
                    if self.should_stop or collected >= max_results:
                        break

                    self._log(f"\n--- 키워드 [{kw_idx+1}/{len(search_keywords)}] '{keyword}' 검색 ---")
                    self._progress(collected, max_results, f"'{keyword}' 검색 중...")

                    search_frame = await navigate_to_search(page, region, keyword)
                    entries = await collect_all_entries(page, search_frame, scan_per_keyword)
                    if not entries:
                        self._log(f"  '{keyword}': 검색 결과 없음")
                        continue
                    self._log(f"  '{keyword}': {len(entries)}개 업체 발견")
                    search_frame = await get_search_frame(page)

                    for idx, entry in enumerate(entries):
                        if self.should_stop or collected >= max_results:
                            break
                        self._progress(collected, max_results, f"[{collected}/{max_results}] '{entry['name']}' 처리 중...")
                        self._log(f"[{collected}/{max_results}] ({idx+1}번째 탐색) '{entry['name']}'")
                        entry["_click_index"] = idx
                        biz = await click_and_extract(
                            page, search_frame, entry, category,
                            context=context,
                            search_region=region,
                        )
                        if biz:
                            dedup_key = biz.place_id or f"{biz.name}|{biz.address or ''}"
                            if dedup_key in seen_ids:
                                self._log(f"  → 중복 업체(기존 수집됨), 건너뛰기")
                            else:
                                seen_ids.add(dedup_key)
                                self.history_ids.add(dedup_key)
                                self.businesses.append(biz)
                                collected += 1
                                email_status = "이메일 있음" if biz.email else "이메일 없음"
                                self._log(f"  → 수집 완료 ({email_status}) ({collected}/{max_results})")
                        await asyncio.sleep(random.uniform(delay_min, delay_max))
                        if (idx+1) % LONG_PAUSE_INTERVAL == 0:
                            await asyncio.sleep(random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX))
                        try:
                            search_frame = await get_search_frame(page)
                        except Exception:
                            await navigate_to_search(page, region, keyword)
                            search_frame = await get_search_frame(page)

            except Exception as e:
                self._log(f"오류: {e}")
        self._progress(max_results, max_results, "완료")
        self._log(f"수집 완료: {len(self.businesses)}건")

    def run_multi_region_mode(self, regions, category, max_results, delay_min, delay_max, keywords=None):
        """여러 지역을 순회하면서 업체를 수집 (중복 제거)"""
        self.is_running = True
        self.should_stop = False
        self.businesses = []
        self.history_ids = load_history()
        asyncio.run(self._multi_region_mode(regions, category, max_results, delay_min, delay_max, keywords))
        save_history(self.history_ids)
        self.is_running = False

    async def _multi_region_mode(self, regions, category, max_results, delay_min, delay_max, keywords=None):
        from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
        from scraper.detail import click_and_extract
        from config import LONG_PAUSE_INTERVAL, LONG_PAUSE_MIN, LONG_PAUSE_MAX

        search_keywords = keywords if keywords and len(keywords) > 0 else [category]
        seen_ids = set(self.history_ids)  # 이전 수집 히스토리 포함
        history_count = len(self.history_ids)
        if history_count > 0:
            self._log(f"기존 수집 히스토리: {history_count}개 업체 (자동 중복 제거)")
        collected = 0
        per_region = max(30, (max_results * 2) // (len(regions) * len(search_keywords)) + 10)

        self._log(f"목표: 업체 {max_results}개 수집")
        self._log(f"검색 키워드: {', '.join(search_keywords)}")
        self._log(f"검색 지역: {len(regions)}개 지역")

        async with create_browser(headed=False) as (browser, context, page):
            for kw_idx, keyword in enumerate(search_keywords):
                if self.should_stop or collected >= max_results:
                    break

                self._log(f"\n{'#'*40}")
                self._log(f"키워드 [{kw_idx+1}/{len(search_keywords)}] '{keyword}'")

                for region_idx, region in enumerate(regions):
                    if self.should_stop or collected >= max_results:
                        break

                    self._log(f"\n{'='*40}")
                    self._log(f"[지역 {region_idx+1}/{len(regions)}] {region} '{keyword}' 검색 중...")
                    self._progress(collected, max_results, f"'{keyword}' - {region} 검색 중...")

                    try:
                        search_frame = await navigate_to_search(page, region, keyword)
                        entries = await collect_all_entries(page, search_frame, per_region)

                        if not entries:
                            self._log(f"  {region}: 검색 결과 없음, 다음 지역으로...")
                            continue

                        self._log(f"  {region}: {len(entries)}개 업체 발견")
                        search_frame = await get_search_frame(page)

                        for idx, entry in enumerate(entries):
                            if self.should_stop or collected >= max_results:
                                break

                            self._progress(collected + 1, max_results, f"[{region}] '{entry['name']}' 처리 중...")
                            self._log(f"  [{collected+1}/{max_results}] '{entry['name']}'")

                            biz = await click_and_extract(
                                page, search_frame, entry, category,
                                context=context,
                                search_region=region,
                            )
                            if biz:
                                dedup_key = biz.place_id or f"{biz.name}|{biz.address or ''}"
                                if dedup_key in seen_ids:
                                    self._log(f"  → 중복 업체(기존 수집됨), 건너뛰기")
                                else:
                                    seen_ids.add(dedup_key)
                                    self.history_ids.add(dedup_key)
                                    self.businesses.append(biz)
                                    collected += 1
                                    email_status = "이메일 있음" if biz.email else "이메일 없음"
                                    self._log(f"  → 수집 완료 ({email_status}) ({collected}/{max_results})")

                            await asyncio.sleep(random.uniform(delay_min, delay_max))
                            if (idx+1) % LONG_PAUSE_INTERVAL == 0:
                                await asyncio.sleep(random.uniform(LONG_PAUSE_MIN, LONG_PAUSE_MAX))

                            try:
                                search_frame = await get_search_frame(page)
                            except Exception:
                                search_frame = await navigate_to_search(page, region, keyword)
                                search_frame = await get_search_frame(page)

                    except Exception as e:
                        self._log(f"  {region} 오류: {e}")
                        continue

        self._progress(max_results, max_results, "완료")
        self._log(f"\n전체 수집 완료: {len(self.businesses)}건 (place_id 기준 중복 제거됨)")

    def run_blog_mode(self, region, category, max_results, delay_min, delay_max):
        self.is_running = True
        self.should_stop = False
        self.businesses = []
        asyncio.run(self._blog_mode(region, category, max_results, delay_min, delay_max))
        self.is_running = False

    async def _blog_mode(self, region, category, max_results, delay_min, delay_max):
        from scraper.blog_search import scrape_blog_search
        async with create_browser(headed=False) as (browser, context, page):
            try:
                self.businesses = await scrape_blog_search(
                    context, page, region, category,
                    max_posts=max_results, delay_min=delay_min, delay_max=delay_max,
                    stop_flag=lambda: self.should_stop,
                    progress_callback=lambda cur, tot, msg: self._progress(cur, tot, msg),
                    log_callback=self._log,
                )
            except Exception as e:
                self._log(f"오류: {e}")
        self._progress(max_results, max_results, "완료")
        self._log(f"수집 완료: {len(self.businesses)}건")


# ─── 메인 앱 ───
class NaverCrawlerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 테마 설정
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        self.title("N플레이스 업체 추출기")
        self.geometry("900x780")
        self.minsize(800, 700)

        # 아이콘 (여러 경로에서 탐색)
        for d in [BASE_DIR, EXE_DIR]:
            icon_path = os.path.join(d, "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
                break

        # 상태
        self.log_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        self.worker = CrawlWorker(self.log_queue, self.progress_queue)
        self.thread = None

        self._build_ui()
        self._setup_logging()
        self._poll_queues()

    def _build_ui(self):
        # ━━━ 상단 헤더 ━━━
        header = ctk.CTkFrame(self, fg_color="#03C75A", corner_radius=0, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)

        # 로고 이미지 (여러 경로에서 탐색)
        logo_path = None
        for d in [BASE_DIR, EXE_DIR]:
            p = os.path.join(d, "logo.png")
            if os.path.exists(p):
                logo_path = p
                break
        if logo_path:
            from PIL import Image
            pil_img = Image.open(logo_path)
            # 로고 비율 유지하면서 헤더 높이(40px)에 맞추기
            logo_h = 40
            ratio = logo_h / pil_img.height
            logo_w = int(pil_img.width * ratio)
            logo_img = ctk.CTkImage(pil_img, size=(logo_w, logo_h))
            ctk.CTkLabel(header, image=logo_img, text="").pack(side="left", padx=(16, 8))

        ctk.CTkLabel(
            header, text="N플레이스 업체 추출기",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="white",
        ).pack(side="left")

        ctk.CTkLabel(
            header, text="v2.1",
            font=ctk.CTkFont(size=12),
            text_color="#b0e8c8",
        ).pack(side="left", padx=8)

        # 테마 전환
        self.theme_switch = ctk.CTkSwitch(
            header, text="다크모드", command=self._toggle_theme,
            text_color="white", font=ctk.CTkFont(size=12),
        )
        self.theme_switch.pack(side="right", padx=16)
        self.theme_switch.select()

        # ━━━ 메인 컨텐츠 ━━━
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=16, pady=(12, 16))

        # ── 설정 카드 ──
        settings_card = ctk.CTkFrame(main, corner_radius=12)
        settings_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            settings_card, text="  크롤링 설정",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, columnspan=6, sticky="w", padx=16, pady=(12, 8))

        # 추출 방법
        ctk.CTkLabel(settings_card, text="추출 방법", font=ctk.CTkFont(size=13)).grid(
            row=1, column=0, sticky="e", padx=(16, 8), pady=6)
        self.mode_var = ctk.StringVar(value="place")
        self.mode_menu = ctk.CTkSegmentedButton(
            settings_card,
            values=["place", "blog"],
            variable=self.mode_var,
            command=self._on_mode_change,
            font=ctk.CTkFont(size=13),
        )
        self.mode_menu.grid(row=1, column=1, columnspan=2, sticky="w", pady=6)

        self.mode_desc = ctk.CTkLabel(
            settings_card,
            text="플레이스 업체 목록에서 수집",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.mode_desc.grid(row=1, column=3, columnspan=3, sticky="w", padx=12, pady=6)

        # 시/도
        ctk.CTkLabel(settings_card, text="시/도", font=ctk.CTkFont(size=13)).grid(
            row=2, column=0, sticky="e", padx=(16, 8), pady=6)
        self.sido_var = ctk.StringVar(value="서울")
        self.sido_combo = ctk.CTkComboBox(
            settings_card, variable=self.sido_var,
            values=list(REGIONS.keys()),
            command=self._on_sido_change,
            width=130, font=ctk.CTkFont(size=13),
        )
        self.sido_combo.grid(row=2, column=1, pady=6, padx=(0, 8))

        # 상세지역
        ctk.CTkLabel(settings_card, text="상세지역", font=ctk.CTkFont(size=13)).grid(
            row=2, column=2, sticky="e", padx=8, pady=6)
        self.region_var = ctk.StringVar(value="서울 강남구")
        self.region_combo = ctk.CTkComboBox(
            settings_card, variable=self.region_var,
            values=REGIONS["서울"],
            width=180, font=ctk.CTkFont(size=13),
        )
        self.region_combo.grid(row=2, column=3, pady=6, padx=(0, 8))

        # 대분류
        ctk.CTkLabel(settings_card, text="대분류", font=ctk.CTkFont(size=13)).grid(
            row=3, column=0, sticky="e", padx=(16, 8), pady=6)
        self.cat_group_var = ctk.StringVar(value="미용·뷰티")
        self.cat_group_combo = ctk.CTkComboBox(
            settings_card, variable=self.cat_group_var,
            values=list(CATEGORIES.keys()),
            command=self._on_cat_group_change,
            width=130, font=ctk.CTkFont(size=13),
        )
        self.cat_group_combo.grid(row=3, column=1, pady=6, padx=(0, 8))

        # 카테고리
        ctk.CTkLabel(settings_card, text="카테고리", font=ctk.CTkFont(size=13)).grid(
            row=3, column=2, sticky="e", padx=8, pady=6)
        self.category_var = ctk.StringVar(value="미용실")
        self.category_combo = ctk.CTkComboBox(
            settings_card, variable=self.category_var,
            values=CATEGORIES["미용·뷰티"],
            width=180, font=ctk.CTkFont(size=13),
        )
        self.category_combo.grid(row=3, column=3, pady=6, padx=(0, 8))

        # 관련 키워드
        ctk.CTkLabel(settings_card, text="관련 키워드", font=ctk.CTkFont(size=13)).grid(
            row=4, column=0, sticky="e", padx=(16, 8), pady=6)
        self.keywords_var = ctk.StringVar(value="")
        self.keywords_entry = ctk.CTkEntry(
            settings_card, textvariable=self.keywords_var,
            placeholder_text="쉼표로 구분 (예: 랩핑, 차량랩핑, PPF)",
            width=500, font=ctk.CTkFont(size=13),
        )
        self.keywords_entry.grid(row=4, column=1, columnspan=3, pady=6, padx=(0, 8), sticky="w")

        # 카테고리 변경 시 관련 키워드 자동 로드 (드롭다운 선택 + 직접 입력 모두)
        self.category_combo.configure(command=self._on_category_change)
        self._category_trace_id = self.category_var.trace_add("write", self._on_category_var_change)

        # 수집 갯수
        ctk.CTkLabel(settings_card, text="수집 갯수", font=ctk.CTkFont(size=13)).grid(
            row=5, column=0, sticky="e", padx=(16, 8), pady=6)
        self.max_var = ctk.StringVar(value="100")
        self.max_combo = ctk.CTkComboBox(
            settings_card, variable=self.max_var,
            values=["100", "300", "500", "1000"],
            width=130, font=ctk.CTkFont(size=13),
        )
        self.max_combo.grid(row=5, column=1, pady=6, padx=(0, 8))

        # 전국 수집 (지역 여러 개 자동 순회)
        self.multi_region_var = ctk.BooleanVar(value=False)
        self.multi_region_check = ctk.CTkCheckBox(
            settings_card, text="전국 수집 (선택한 시/도의 모든 구/군 자동 순회, 200~300개 수집용)",
            variable=self.multi_region_var, font=ctk.CTkFont(size=12),
            command=self._on_multi_region_change,
        )
        self.multi_region_check.grid(row=5, column=2, columnspan=4, sticky="w", padx=8, pady=6)

        # 심층탐색
        self.deep_var = ctk.BooleanVar(value=False)
        self.deep_check = ctk.CTkCheckBox(
            settings_card, text="심층탐색 (블로그/홈페이지에서 010/이메일 추가 탐색)",
            variable=self.deep_var, font=ctk.CTkFont(size=12),
        )
        self.deep_check.grid(row=6, column=2, columnspan=4, sticky="w", padx=8, pady=(6, 12))

        # ── 버튼 바 ──
        btn_bar = ctk.CTkFrame(main, fg_color="transparent")
        btn_bar.pack(fill="x", pady=(0, 8))

        self.start_btn = ctk.CTkButton(
            btn_bar, text="크롤링 시작", width=140, height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#03C75A", hover_color="#02a84e",
            command=self._start_crawl,
        )
        self.start_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            btn_bar, text="중지", width=80, height=38,
            font=ctk.CTkFont(size=14),
            fg_color="#e74c3c", hover_color="#c0392b",
            state="disabled",
            command=self._stop_crawl,
        )
        self.stop_btn.pack(side="left", padx=(0, 8))

        self.download_btn = ctk.CTkButton(
            btn_bar, text="엑셀 다운로드", width=140, height=38,
            font=ctk.CTkFont(size=14),
            fg_color="#2980b9", hover_color="#2471a3",
            state="disabled",
            command=self._download_excel,
        )
        self.download_btn.pack(side="left")

        self.count_label = ctk.CTkLabel(
            btn_bar, text="",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.count_label.pack(side="right", padx=8)

        # ── 진행률 ──
        self.progress_bar = ctk.CTkProgressBar(main, height=6, corner_radius=3)
        self.progress_bar.pack(fill="x", pady=(0, 4))
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(
            main, text="대기 중",
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self.progress_label.pack(anchor="w")

        # ── 결과 테이블 (스크롤 가능) ──
        table_frame = ctk.CTkFrame(main, corner_radius=12)
        table_frame.pack(fill="both", expand=True, pady=(8, 8))

        # 테이블 헤더
        header_frame = ctk.CTkFrame(table_frame, fg_color="#03C75A", corner_radius=0, height=32)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        cols = [("No", 35), ("업체명", 120), ("대표전화", 100), ("010번호", 100),
                ("이메일", 120), ("네이버ID", 90), ("주소", 200)]
        self._col_widths = cols
        for text, w in cols:
            ctk.CTkLabel(
                header_frame, text=text, width=w,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="white",
            ).pack(side="left", padx=2)

        self.table_scroll = ctk.CTkScrollableFrame(table_frame, corner_radius=0)
        self.table_scroll.pack(fill="both", expand=True)
        self._table_rows = 0

        # ── 로그 ──
        ctk.CTkLabel(
            main, text="실행 로그",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(4, 2))

        self.log_box = ctk.CTkTextbox(
            main, height=120,
            font=ctk.CTkFont(family="Consolas", size=11),
            corner_radius=8,
        )
        self.log_box.pack(fill="x")
        self.log_box.configure(state="disabled")

    # ─── 이벤트 핸들러 ───

    def _toggle_theme(self):
        if self.theme_switch.get():
            ctk.set_appearance_mode("dark")
        else:
            ctk.set_appearance_mode("light")

    def _on_mode_change(self, mode):
        if mode == "place":
            self.mode_desc.configure(text="플레이스 업체 목록에서 수집")
            self.deep_check.configure(state="normal")
        else:
            self.mode_desc.configure(text="블로그 최신순 포스트에서 업체 정보 수집")
            self.deep_var.set(False)
            self.deep_check.configure(state="disabled")

    def _on_multi_region_change(self):
        if self.multi_region_var.get():
            # 전국 수집 모드: 상세지역 비활성화
            self.region_combo.configure(state="disabled")
        else:
            self.region_combo.configure(state="normal")

    def _on_sido_change(self, sido):
        areas = REGIONS.get(sido, [])
        self.region_combo.configure(values=areas)
        if areas:
            self.region_var.set(areas[0])

    def _on_cat_group_change(self, group):
        items = CATEGORIES.get(group, [])
        self.category_combo.configure(values=items)
        if items:
            self.category_var.set(items[0])
            self._on_category_change(items[0])

    def _on_category_change(self, category):
        """카테고리 드롭다운 선택 시 관련 키워드 자동 로드"""
        keywords = KEYWORD_GROUPS.get(category, [category])
        self.keywords_var.set(", ".join(keywords))

    def _on_category_var_change(self, *args):
        """카테고리 직접 입력 시에도 관련 키워드 자동 로드"""
        category = self.category_var.get().strip()
        if category:
            keywords = KEYWORD_GROUPS.get(category, [category])
            # trace 안에서 다른 StringVar 변경 시 무한루프 방지
            current = self.keywords_var.get()
            new_val = ", ".join(keywords)
            if current != new_val:
                self.keywords_var.set(new_val)

    def _setup_logging(self):
        handler = QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    def _poll_queues(self):
        # 로그
        while not self.log_queue.empty():
            try:
                msg = self.log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert(END, msg + "\n")
                self.log_box.see(END)
                self.log_box.configure(state="disabled")
            except queue.Empty:
                break

        # 진행률
        while not self.progress_queue.empty():
            try:
                current, total, status = self.progress_queue.get_nowait()
                if total > 0:
                    self.progress_bar.set(current / total)
                    self.progress_label.configure(text=f"{current}/{total}  {status}")
                else:
                    self.progress_bar.set(0)
                    self.progress_label.configure(text=status)
            except queue.Empty:
                break

        # 테이블 갱신
        if self.worker.businesses and len(self.worker.businesses) > self._table_rows:
            self._update_table()

        # 작업 완료
        if self.thread and not self.thread.is_alive():
            self._on_crawl_done()
            self.thread = None

        self.after(200, self._poll_queues)

    def _update_table(self):
        for idx in range(self._table_rows, len(self.worker.businesses)):
            biz = self.worker.businesses[idx]
            row_frame = ctk.CTkFrame(self.table_scroll, fg_color="transparent", height=28)
            row_frame.pack(fill="x", pady=1)

            values = [
                str(idx + 1), biz.name or "", biz.phone or "",
                biz.personal_phone or "", biz.email or "",
                biz.naver_id or "", biz.address or "",
            ]
            for (_, w), val in zip(self._col_widths, values):
                ctk.CTkLabel(
                    row_frame, text=val, width=w,
                    font=ctk.CTkFont(size=11),
                    anchor="w",
                ).pack(side="left", padx=2)

        self._table_rows = len(self.worker.businesses)
        self.count_label.configure(text=f"수집: {self._table_rows}건")

    def _start_crawl(self):
        region = self.region_var.get().strip()
        category = self.category_var.get().strip()

        if region.endswith(" 전체"):
            region = region.replace(" 전체", "")

        try:
            max_results = int(self.max_var.get())
        except ValueError:
            max_results = 50

        if not region or not category:
            from tkinter import messagebox
            messagebox.showwarning("입력 오류", "지역과 카테고리를 선택해주세요.")
            return

        # 전국 수집 모드가 아닐 때만 상한 적용
        if not self.multi_region_var.get() and max_results > MAX_RESULTS:
            max_results = MAX_RESULTS

        # UI 초기화
        for widget in self.table_scroll.winfo_children():
            widget.destroy()
        self._table_rows = 0
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", END)
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.count_label.configure(text="")

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.download_btn.configure(state="disabled")

        mode = self.mode_var.get()
        deep = self.deep_var.get()

        # 관련 키워드 파싱 (쉼표로 구분, 빈 값 제거)
        keywords_text = self.keywords_var.get().strip()
        keywords = [k.strip() for k in keywords_text.split(",") if k.strip()] if keywords_text else [category]

        if mode == "place" and self.multi_region_var.get():
            # 전국 수집 모드: 선택한 시/도의 모든 구/군 순회
            sido = self.sido_var.get()
            sub_regions = [r for r in REGIONS.get(sido, []) if not r.endswith(" 전체")]
            if not sub_regions:
                sub_regions = [sido]
            self.thread = threading.Thread(
                target=self.worker.run_multi_region_mode,
                args=(sub_regions, category, max_results,
                      DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, keywords),
                daemon=True,
            )
        elif mode == "place":
            self.thread = threading.Thread(
                target=self.worker.run_place_mode,
                args=(region, category, max_results, deep,
                      DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX, keywords),
                daemon=True,
            )
        else:
            self.thread = threading.Thread(
                target=self.worker.run_blog_mode,
                args=(region, category, max_results,
                      DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX),
                daemon=True,
            )
        self.thread.start()

    def _stop_crawl(self):
        self.worker.should_stop = True
        self.stop_btn.configure(state="disabled")
        self.start_btn.configure(state="normal")
        self.log_queue.put("중지 요청됨... 완료 후 재시작 가능합니다.")

    def _on_crawl_done(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if self.worker.businesses:
            self.download_btn.configure(state="normal")
        self._update_table()

    def _download_excel(self):
        if not self.worker.businesses:
            return

        region = self.region_var.get().strip().replace(" ", "_")
        category = self.category_var.get().strip().replace(" ", "_")
        mode = self.mode_var.get()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"naver_{mode}_{region}_{category}_{timestamp}.xlsx"

        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel 파일", "*.xlsx")],
            initialfile=default_name,
            title="엑셀 파일 저장",
        )

        if filepath:
            try:
                export_to_excel(self.worker.businesses, filepath)
                from tkinter import messagebox
                messagebox.showinfo(
                    "저장 완료",
                    f"{len(self.worker.businesses)}건 저장 완료\n{filepath}",
                )
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("저장 실패", str(e))


if __name__ == "__main__":
    try:
        if not ensure_browser_installed():
            import tkinter.messagebox as mb
            mb.showerror(
                "브라우저 설치 필요",
                "Chromium 브라우저 자동 설치에 실패했습니다.\n\n"
                "해결 방법:\n"
                "1. 명령 프롬프트(CMD)를 열어주세요\n"
                "2. 다음 명령어를 입력하세요:\n"
                "   playwright install chromium\n\n"
                "설치 후 프로그램을 다시 실행해주세요.",
            )
            sys.exit(1)

        app = NaverCrawlerApp()
        app.mainloop()
    except Exception as e:
        # 에러를 로그 파일에 기록
        error_log = os.path.join(EXE_DIR, "error.log")
        with open(error_log, "w", encoding="utf-8") as f:
            f.write(f"프로그램 실행 중 오류가 발생했습니다:\n\n")
            f.write(traceback.format_exc())
        # 사용자에게도 표시
        try:
            import tkinter.messagebox as mb
            mb.showerror(
                "오류 발생",
                f"프로그램 실행 중 오류가 발생했습니다:\n\n"
                f"{type(e).__name__}: {e}\n\n"
                f"상세 로그: {error_log}",
            )
        except Exception:
            pass
        sys.exit(1)
