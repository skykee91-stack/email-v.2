import sys, io, asyncio, logging, time, random

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')

from scraper.browser import create_browser
from scraper.search import navigate_to_search, collect_all_entries, get_search_frame
from scraper.detail import click_and_extract
from scraper.blog_search import scrape_blog_search
from export.excel import export_to_excel

PLACE_TESTS = [
    ('서울 강남', '치과'),
    ('부산 해운대', '헬스장'),
    ('대구', '세탁소'),
    ('인천 부평', '꽃집'),
    ('경기 수원', '인테리어'),
]

BLOG_TESTS = [
    ('서울 마포', '청소업체'),
    ('부산', '이사업체'),
    ('대전', '에어컨설치'),
    ('경기 성남', '피부관리'),
    ('인천', '자동차정비'),
]


async def run_place(context, page, region, category):
    results = []
    sf = await navigate_to_search(page, region, category)
    entries = await collect_all_entries(page, sf, 100)
    sf = await get_search_frame(page)
    for i, e in enumerate(entries):
        b = await click_and_extract(page, sf, e, category, context=context)
        if b:
            results.append(b)
        await asyncio.sleep(random.uniform(1.5, 2.5))
        if (i + 1) % 20 == 0:
            await asyncio.sleep(random.uniform(8, 12))
        try:
            sf = await get_search_frame(page)
        except Exception:
            await navigate_to_search(page, region, category)
            sf = await get_search_frame(page)
    return results


async def run_blog(context, page, region, category):
    return await scrape_blog_search(
        context, page, region, category,
        max_posts=100, delay_min=1.5, delay_max=2.5,
    )


async def main():
    all_results = []

    async with create_browser(headed=False) as (browser, context, page):
        for region, cat in PLACE_TESTS:
            start = time.time()
            try:
                results = await run_place(context, page, region, cat)
            except Exception as ex:
                print(f'[place] {region} {cat}: ERROR {ex}', flush=True)
                all_results.append(('place', region, cat, 0, 0, 0, 0, 0, 0, 0))
                continue
            elapsed = time.time() - start
            wp = sum(1 for b in results if b.phone)
            wa = sum(1 for b in results if b.address)
            wn = sum(1 for b in results if b.naver_id)
            w010 = sum(1 for b in results if b.personal_phone)
            we = sum(1 for b in results if b.email)
            all_results.append(('place', region, cat, len(results), wp, wa, wn, w010, we, elapsed))
            print(f'[place] {region} {cat}: {len(results)}건 T:{wp} A:{wa} ID:{wn} 010:{w010} E:{we} ({elapsed:.0f}s)', flush=True)

        for region, cat in BLOG_TESTS:
            start = time.time()
            try:
                results = await run_blog(context, page, region, cat)
            except Exception as ex:
                print(f'[blog]  {region} {cat}: ERROR {ex}', flush=True)
                all_results.append(('blog', region, cat, 0, 0, 0, 0, 0, 0, 0))
                continue
            elapsed = time.time() - start
            wp = sum(1 for b in results if b.phone)
            wa = sum(1 for b in results if b.address)
            wn = sum(1 for b in results if b.naver_id)
            w010 = sum(1 for b in results if b.personal_phone)
            we = sum(1 for b in results if b.email)
            all_results.append(('blog', region, cat, len(results), wp, wa, wn, w010, we, elapsed))
            print(f'[blog]  {region} {cat}: {len(results)}건 T:{wp} A:{wa} ID:{wn} 010:{w010} E:{we} ({elapsed:.0f}s)', flush=True)

    print(flush=True)
    print('=' * 95, flush=True)
    print(f'{"모드":<7} {"지역":<12} {"카테고리":<10} {"수집":>5} {"전화":>5} {"주소":>5} {"ID":>5} {"010":>5} {"이메일":>6} {"시간":>6}', flush=True)
    print('-' * 95, flush=True)
    for r in all_results:
        mode, region, cat = r[0], r[1], r[2]
        cnt, wp, wa, wn, w010, we, el = r[3], r[4], r[5], r[6], r[7], r[8], r[9]
        print(f'{mode:<7} {region:<12} {cat:<10} {cnt:>5} {wp:>5} {wa:>5} {wn:>5} {w010:>5} {we:>6} {el:>5.0f}s', flush=True)


asyncio.run(main())
