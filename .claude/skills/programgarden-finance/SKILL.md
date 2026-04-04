---
name: programgarden-finance
description: programgarden-finance 라이브러리 API 가이드. LS증권 해외주식/해외선물 API 호출 패턴, TR코드, InBlock 구조 참조. Use when writing or modifying LS증권 API calls.
user-invocable: false
---

# programgarden-finance API 가이드

LS증권 API를 래핑한 Python 라이브러리. 이 프로젝트의 모든 증권 API 호출은 이 라이브러리를 통해 이루어진다.

## 기본 구조

```python
from programgarden_finance import LS
from programgarden_finance.ls.models import SetupOptions

ls = LS()

# 실전 로그인 (해외주식)
await ls.async_login(appkey="...", appsecretkey="...")

# 모의투자 로그인 (해외선물 - HKEX만 지원)
await ls.async_login(appkey="...", appsecretkey="...", paper_trading=True)
```

## 도메인 접근

```python
stock = ls.overseas_stock()        # 해외주식
futures = ls.overseas_futureoption()  # 해외선물옵션
```

각 도메인은 하위 카테고리를 가진다:
- `.market()` — 시세 조회
- `.chart()` — 차트 데이터
- `.accno()` — 계좌 조회
- `.order()` — 주문
- `.real()` — 실시간 WebSocket

## 요청 패턴

```python
# 단건 비동기 요청
request = stock.market().g3101(inblock, setup_options)
result = await request.req_async()  # → OutBlock

# 재시도 포함 요청
await request.retry_req_async(callback)

# 페이징 자동 처리 (연속 조회)
await request.occurs_req_async(callback)
```

### SetupOptions (속도 제한)

```python
opts = SetupOptions(
    rate_limit_count=3,      # N건
    rate_limit_seconds=1,    # M초당
    on_rate_limit="wait",    # "wait" | "raise"
)
```

## 해외주식 TR코드

### 시세
| TR | 용도 | InBlock |
|----|------|---------|
| `g3101` | 현재가 조회 | `G3101InBlock(symbol, exchange_code)` |
| `g3102` | 시간대별 조회 | `G3102InBlock(symbol, exchange_code)` |
| `g3106` | 호가 조회 | `G3106InBlock(symbol, exchange_code)` |
| `g3190` | 종목 마스터 (목록) | `G3190InBlock(exchange_code)` |

### 차트
| TR | 용도 | InBlock |
|----|------|---------|
| `g3204` | 일/주/월/년 차트 | `G3204InBlock(symbol, exchange_code, period, count)` |

### 계좌
| TR | 용도 | InBlock |
|----|------|---------|
| `COSOQ02701` | 예수금 조회 | `COSOQ02701InBlock1()` |
| `COSOQ00201` | 보유종목 조회 | `COSOQ00201InBlock1(exchange_code)` |

### 주문
| TR | 용도 | InBlock |
|----|------|---------|
| `COSAT00301` | 신규주문 (매수/매도) | `COSAT00301InBlock1(symbol, exchange_code, side, qty, price, order_type)` |
| `COSAT00311` | 정정/취소 | `COSAT00311InBlock1(...)` |

### 실시간 (WebSocket)
| 코드 | 용도 | 비고 |
|------|------|------|
| `GSC` | 실시간 체결 | 체결가, 체결량, 시간 |
| `GSH` | 실시간 호가 | 잔량이 항상 0으로 올 수 있음 → REST g3106 사용 권장 |

### 거래소 코드
- `81` = NYSE / AMEX
- `82` = NASDAQ

## 해외선물 TR코드

### 시세
| TR | 용도 | InBlock |
|----|------|---------|
| `o3101` | 종목 마스터 | `O3101InBlock(exchange)` |
| `o3105` | 현재가 | `O3105InBlock(symbol)` |

### 차트
| TR | 용도 | InBlock |
|----|------|---------|
| `o3108` | 일/주/월 차트 | `O3108InBlock(symbol, period, count)` |

### 계좌
| TR | 용도 | InBlock |
|----|------|---------|
| `CIDBQ03000` | 예수금/증거금 | `CIDBQ03000InBlock1()` |
| `CIDBQ01500` | 미결제잔고 (보유포지션) | `CIDBQ01500InBlock1()` |

### 주문
| TR | 용도 | InBlock |
|----|------|---------|
| `CIDBT00100` | 신규/청산 주문 | `CIDBT00100InBlock1(symbol, side, qty, price, order_type)` |

### 실시간 (WebSocket)
| 코드 | 용도 |
|------|------|
| `OVC` | 해외선물 실시간 체결 |
| `OVH` | 해외선물 실시간 호가 |
| `TC1/TC2/TC3` | 주문 체결 통보 |

### 모의투자 지원 상품 (HKEX)
HSI, HMH, HCEI, HMCE, HTI, HCHH, MCA, CUS

## Import 패턴

```python
# InBlock은 각 TR의 blocks 모듈에서 import
from programgarden_finance.ls.overseas_stock.market.g3101.blocks import G3101InBlock
from programgarden_finance.ls.overseas_stock.chart.g3204.blocks import G3204InBlock
from programgarden_finance.ls.overseas_stock.accno.COSOQ02701.blocks import COSOQ02701InBlock1
from programgarden_finance.ls.overseas_stock.order.COSAT00301.blocks import COSAT00301InBlock1

# 선물
from programgarden_finance.ls.overseas_futureoption.market.o3101.blocks import O3101InBlock
from programgarden_finance.ls.overseas_futureoption.market.o3105.blocks import O3105InBlock
from programgarden_finance.ls.overseas_futureoption.chart.o3108.blocks import O3108InBlock
from programgarden_finance.ls.overseas_futureoption.accno.CIDBQ03000.blocks import CIDBQ03000InBlock1
from programgarden_finance.ls.overseas_futureoption.order.CIDBT00100.blocks import CIDBT00100InBlock1
```

## 제약 사항

- API 속도 제한: 초당 3~5건 (SetupOptions으로 자동 대기)
- GSH 호가: 잔량이 0으로 올 수 있음 → 호가 잔량 필요 시 REST g3106 사용
- 모의투자: 해외선물만 가능 (HKEX 상품만), 해외주식은 실전만
- 비동기 전용: `req_async()`, `retry_req_async()`, `occurs_req_async()`

## 참고 링크

- 예제: https://github.com/programgarden/programgarden/tree/main/src/finance/example
- 가이드: https://programgarden.gitbook.io/docs/develop/finance_guide
