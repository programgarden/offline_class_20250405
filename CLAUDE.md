# CLAUDE.md

## 프로젝트 개요
터틀 트레이딩 전략 기반 자동매매 시스템. LS증권 API를 통해 해외주식(미국 NYSE/NASDAQ)과 해외선물(홍콩 HKEX)을 자동 매매한다.

## 기술 스택
- Python 3.13 | FastAPI | APScheduler | aiosqlite
- programgarden-finance (LS증권 API 래퍼)
- python-telegram-bot (알림)
- yfinance (재무 데이터 스크리닝)

## 실행
```bash
python main.py          # 웹 대시보드 + 봇 실행 (http://localhost:8000)
```

## 프로젝트 구조
PROJECT_MAP.md 참조.

## 핵심 규칙
- 커밋 메시지: 한국어 허용, `feat:/fix:/refactor:/docs:/chore:` prefix
- 응답 언어: 한국어
- 환경변수: `.env` 파일 (LS_APPKEY, LS_APPSECRETKEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 등)
- DB: SQLite (`data/trading.db`), aiosqlite 비동기
- API 키는 웹 대시보드에서도 설정 가능 (DB에 저장, 앱 시작 시 config에 반영)

## 테스트
```bash
pytest                  # 전체 테스트
pytest tests/test_xxx.py  # 개별 테스트
```

## 주의사항
- `venv/` 디렉토리는 검색/수정 대상에서 제외할 것
- `data/` 디렉토리는 런타임 생성 (로그, DB)
- 해외선물은 모의투자(paper) 기본, 실전 키가 있으면 실전 가능
- 웹 대시보드는 단일 HTML (`web/dashboard.html`) + FastAPI REST API
