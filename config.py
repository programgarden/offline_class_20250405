import os
from dotenv import load_dotenv

load_dotenv()

# LS증권 API (해외주식)
LS_APPKEY = os.getenv("LS_APPKEY", "")
LS_APPSECRETKEY = os.getenv("LS_APPSECRETKEY", "")

# LS증권 API (국내주식)
KRX_APPKEY = os.getenv("APPKEY_KOREA", os.getenv("KRX_APPKEY", ""))
KRX_APPSECRETKEY = os.getenv("APPSECRET_KOREA", os.getenv("KRX_APPSECRETKEY", ""))

# 텔레그램
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 거래소 코드
EXCHANGE_NYSE = "81"
EXCHANGE_NASDAQ = "82"

# 터틀 전략 기본값 (텔레그램 /set 명령으로 변경 가능)
DONCHIAN_PERIOD = 20          # 돈치안 채널 기간 (일)
ATR_PERIOD = 20               # ATR 계산 기간 (일)
ATR_MULTIPLIER = 3.0          # 트레일링 스탑 ATR 배수
MAX_STOCKS = 5                # 최대 보유 종목 수
CAPITAL_RATIO = 50            # 예수금 사용 비율 (%)
MA_SHORT = 20                 # 단기 이동평균
MA_LONG = 60                  # 장기 이동평균

# 리스크 관리
RISK_WARN_PCT = 4.0           # 4% 손실 경고 → 마이너스 종목 청산
RISK_STOP_PCT = 5.0           # 5% 손실 비상 → 전종목 청산 + 매매 중단

# 재무 필터 기준
MIN_MARKET_CAP = 1_000_000_000   # 시가총액 최소 10억 달러
MAX_DEBT_RATIO = 200             # 부채비율 최대 200%
MAX_PER = 50                     # PER 최대 50
MIN_PER = 0                      # PER 최소 0 (적자기업 제외)

# DB 경로
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "trading.db")

# API 속도 제한
RATE_LIMIT_COUNT = 3
RATE_LIMIT_SECONDS = 1

# 재시도 설정
API_MAX_RETRIES = 3           # API 호출 최대 재시도 횟수
API_RETRY_BASE_DELAY = 2      # 재시도 기본 대기(초), 지수 백오프 적용
WS_MAX_RETRIES = 5            # WebSocket 연결 최대 재시도
WS_RETRY_BASE_DELAY = 3       # WebSocket 재시도 기본 대기(초)

# 운영 모드
MODE_DRY = "dry"
MODE_LIVE = "live"
DEFAULT_MODE = MODE_DRY

# ── 해외선물 설정 ────────────────────────────────────────

# 해외선물 모의투자 API
FUTURES_LS_APPKEY = os.getenv("FUTURES_LS_APPKEY", os.getenv("APPKEY_FUTURE_FAKE", LS_APPKEY))
FUTURES_LS_APPSECRETKEY = os.getenv("FUTURES_LS_APPSECRETKEY", os.getenv("APPSECRET_FUTURE_FAKE", LS_APPSECRETKEY))

# 해외선물 실전투자 API
FUTURES_LIVE_APPKEY = os.getenv("FUTURES_LIVE_APPKEY", "")
FUTURES_LIVE_APPSECRETKEY = os.getenv("FUTURES_LIVE_APPSECRETKEY", "")

# 거래 대상 선물 상품 목록 (홍콩거래소 - 모의투자 지원)
FUTURES_SYMBOLS = [
    {"base": "HMH", "name": "미니 항셍지수", "exchange": "HKEX", "quarterly": True},
    {"base": "HMCE", "name": "미니 H주지수", "exchange": "HKEX", "quarterly": True},
    {"base": "MCA", "name": "MSCI China A50", "exchange": "HKEX", "quarterly": False},
    {"base": "HSI", "name": "항셍지수", "exchange": "HKEX", "quarterly": False},
    {"base": "HTI", "name": "항셍테크지수", "exchange": "HKEX", "quarterly": False},
    {"base": "HCEI", "name": "H주지수", "exchange": "HKEX", "quarterly": False},
]

# 선물 월코드
FUTURES_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}

# 선물 분기 만기월
FUTURES_QUARTER_MONTHS = [3, 6, 9, 12]

# 선물 터틀 전략 기본값
FUTURES_DONCHIAN_PERIOD = 20
FUTURES_ATR_PERIOD = 20
FUTURES_ATR_MULTIPLIER = 3.0
FUTURES_MAX_CONTRACTS = 5       # 최대 동시 보유 종목 수
FUTURES_RISK_PER_TRADE = 2.0    # 1종목당 리스크 비율 (예수금 대비 %)

# 선물 리스크 관리 (증거금 대비)
FUTURES_RISK_WARN_PCT = 3.0     # 3% 손실 경고 → 마이너스 종목 청산
FUTURES_RISK_STOP_PCT = 5.0     # 5% 손실 비상 → 전종목 청산 + 매매 중단
FUTURES_MARGIN_LIMIT_PCT = 80.0 # 증거금 사용률 80% 초과 시 신규 진입 차단

# 선물 API 속도 제한
FUTURES_RATE_LIMIT_COUNT = 5
FUTURES_RATE_LIMIT_SECONDS = 1

# ── 국내주식 설정 ────────────────────────────────────────
KRX_DONCHIAN_PERIOD = 20
KRX_ATR_PERIOD = 20
KRX_ATR_MULTIPLIER = 3.0
KRX_MAX_STOCKS = 5
KRX_CAPITAL_RATIO = 50          # 예수금 사용 비율(%)
KRX_RISK_WARN_PCT = 4.0
KRX_RISK_STOP_PCT = 5.0

# 국내 거래시간 (KST): 09:00 ~ 15:30
# 운영 시드 종목 (대형주 위주, 사용자가 .env / 대시보드에서 갈음 가능)
KRX_DEFAULT_UNIVERSE = [
    {"symbol": "005930", "name": "삼성전자"},
    {"symbol": "000660", "name": "SK하이닉스"},
    {"symbol": "035420", "name": "NAVER"},
    {"symbol": "035720", "name": "카카오"},
    {"symbol": "005380", "name": "현대차"},
    {"symbol": "051910", "name": "LG화학"},
    {"symbol": "006400", "name": "삼성SDI"},
    {"symbol": "207940", "name": "삼성바이오로직스"},
    {"symbol": "068270", "name": "셀트리온"},
    {"symbol": "373220", "name": "LG에너지솔루션"},
]

KRX_RATE_LIMIT_COUNT = 3
KRX_RATE_LIMIT_SECONDS = 1

# 홍콩거래소 거래 시간 (한국시간 KST = HKT + 1시간)
# T세션: 10:15~13:00, 14:00~17:30 KST
# T+1세션(야간): 18:15~04:00 KST
