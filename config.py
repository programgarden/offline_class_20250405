import os
from dotenv import load_dotenv

load_dotenv()

# LS증권 API
LS_APPKEY = os.getenv("LS_APPKEY", "")
LS_APPSECRETKEY = os.getenv("LS_APPSECRETKEY", "")

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
