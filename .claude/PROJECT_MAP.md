# PROJECT_MAP
@generated: 2026-04-04T13:00:00
@type: single-app
@stack: Python 3.13 | FastAPI | APScheduler | aiosqlite | programgarden-finance

## TREE
config.py               [전략 파라미터, API 키, 거래소 설정]
main.py                 [FastAPI 앱 진입점, lifespan 관리]
scheduler.py            [해외주식 스케줄러 (TurtleScheduler, APScheduler cron)]
futures_scheduler.py    [해외선물 스케줄러 (FuturesScheduler, HKEX 시간)]
analyzer/               [2 src .py]
  trend_analyzer.py     [돈치안/ATR/이평선/모멘텀 계산]
  stock_screener.py     [yfinance 재무 필터 + LS증권 시세 스크리닝]
trader/                 [6 src .py]
  ls_client.py          [LSClient — 해외주식 API (programgarden-finance 래퍼)]
  futures_client.py     [FuturesClient — 해외선물 API (모의/실전)]
  engine.py             [TradingEngine — 주식 매매 실행 (매수/매도/스탑)]
  futures_engine.py     [FuturesEngine — 선물 매매 실행]
  realtime.py           [RealtimeMonitor — 주식 실시간 체결 WebSocket]
  futures_realtime.py   [FuturesRealtimeMonitor — 선물 실시간 체결 WebSocket]
database/               [3 src .py]
  models.py             [SQLite 스키마 정의 + init_db()]
  repository.py         [비동기 CRUD (설정, 분석, 포지션, 거래, 리포트)]
risk/                   [2 src .py]
  risk_manager.py       [RiskManager — 주식 일일손익 감시, 경고/비상 청산]
  futures_risk.py       [FuturesRiskManager — 선물 증거금/손익 감시]
tgbot/                  [1 src .py]
  bot.py                [TelegramBot — 알림 발송, /set /status /help 명령]
web/                    [1 src .py, 1 .html]
  api.py                [FastAPI 라우터 — 15 endpoints (주식 7 + 선물 6 + 키관리 2)]
  dashboard.html        [단일 HTML 대시보드 (주식 + 선물 탭)]
tests/                  [6 test .py]

## KEY_FILES
main.py → FastAPI lifespan (DB 초기화 → API 키 로드 → 주식봇 시작 → 선물봇 시작)
scheduler.py → TurtleScheduler (9:15 분석, 장중 매수/스탑 체크, 일일리포트, 리스크 모니터링)
futures_scheduler.py → FuturesScheduler (HKEX T/T+1 세션, 30분 주기 분석/매수/스탑, 헬스체크)
config.py → 모든 전략 파라미터 + API 키 (텔레그램 /set 명령으로 런타임 변경 가능)
web/api.py → 15 REST endpoints: /api/status, settings, control, trades, positions, futures/*, keys
database/repository.py → 전체 DB 접근 계층 (주식 12 fn + 선물 10 fn + 설정 3 fn)

## PATTERNS
- Turtle Trading: 돈치안 채널 돌파 진입, ATR 기반 포지션 사이징 + 트레일링 스탑
- Dual Bot Architecture: 해외주식(TurtleScheduler) + 해외선물(FuturesScheduler) 독립 운영, 텔레그램 공유
- programgarden-finance: LS증권 API 래퍼 (ls_stock, ls_overseas_futures 모듈)
- APScheduler Cron: 거래소별 시간대 스케줄링 (NYSE=ET, HKEX=HKT)
- WebSocket Realtime: 실시간 체결가 모니터링 → 트레일링 스탑 자동 실행
- Risk Management: 2단계 (경고→비상) 일일손익 기반 리스크 관리
- Settings Cascade: .env → DB → 텔레그램 /set → config 모듈 반영

## DEPS
programgarden-finance==1.4.3 | aiosqlite>=0.20.0 | APScheduler>=3.10.4 | python-telegram-bot>=21.0 | python-dotenv>=1.0.0 | yfinance>=0.2.36 | fastapi>=0.115.0 | uvicorn>=0.32.0

## CONVENTIONS
- language: 한국어 (코드 주석, 커밋 메시지, 로그 메시지)
- commit: feat:/fix:/refactor:/docs:/chore: prefix, 한국어 본문
- naming: snake_case (Python), 모듈명=역할 (engine=매매실행, client=API통신, scheduler=스케줄링)
- config: 환경변수(.env) + DB 설정 + 텔레그램 명령 3단계 오버라이드
- async: 전체 비동기 (aiosqlite, httpx via programgarden-finance, asyncio)
- venv: Python 3.13, venv/ 디렉토리 (검색 제외)
