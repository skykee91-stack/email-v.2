"""크롤러 설정 상수"""

# 네이버 맵 검색 URL
NAVER_MAP_URL = "https://map.naver.com/p/search/{query}"

# 요청 간 딜레이 (초) - 프록시 사용 시 짧게
DEFAULT_DELAY_MIN = 0.5
DEFAULT_DELAY_MAX = 1.5

# 장기 대기 간격 (N건마다 장기 대기) - 프록시 사용 시 완화
LONG_PAUSE_INTERVAL = 50
LONG_PAUSE_MIN = 3.0
LONG_PAUSE_MAX = 5.0

# 최대 수집 수 (안전 상한, 전국 수집 모드에서는 이 제한 무시)
MAX_RESULTS = 1000

# 타임아웃 (밀리초) - 빠르게 건너뛰기
PAGE_LOAD_TIMEOUT = 10000
ELEMENT_TIMEOUT = 7000

# 재시도 설정
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 3.0
