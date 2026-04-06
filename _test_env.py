import os, json
val = os.environ.get('SCRAPE_CONFIG', '{}')
with open(r'C:/Users/a/naver_place_scraper/_envtest.txt', 'w', encoding='utf-8') as f:
    f.write(val)
