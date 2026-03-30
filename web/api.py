"""웹 대시보드 API: FastAPI 라우터"""
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

import config
from database import repository as repo

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

# 스케줄러 참조 (main에서 주입)
_scheduler = None

# LS API 캐시 (TR별 분당 호출 제한 대응)
_cache = {"balance": {}, "holdings": [], "_balance_at": 0, "_holdings_at": 0}
CACHE_TTL = 30  # 30초 캐시


def set_scheduler(scheduler):
    global _scheduler
    _scheduler = scheduler


async def _get_cached_balance():
    now = time.time()
    if now - _cache["_balance_at"] < CACHE_TTL and _cache["balance"]:
        return _cache["balance"]
    try:
        _cache["balance"] = await _scheduler.client.get_balance()
        _cache["_balance_at"] = now
    except Exception as e:
        log.warning("예수금 조회 실패: %s", e)
    return _cache["balance"]


async def _get_cached_holdings():
    now = time.time()
    if now - _cache["_holdings_at"] < CACHE_TTL and _cache["holdings"]:
        return _cache["holdings"]
    try:
        _cache["holdings"] = await _scheduler.client.get_holdings()
        _cache["_holdings_at"] = now
    except Exception as e:
        log.warning("보유종목 조회 실패: %s", e)
    return _cache["holdings"]


@router.get("/status")
async def get_status():
    """봇 상태 + 예수금 + 보유종목"""
    settings = await repo.get_all_settings()
    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M") + " (미국동부시간)"
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M") + " (한국시간)"

    result = {
        "mode": settings.get("mode", config.DEFAULT_MODE),
        "trading_paused": settings.get("trading_paused") == "1",
        "risk_stopped": settings.get("risk_stopped") == "1",
        "time_et": now_et,
        "time_kst": now_kst,
        "bot_running": _scheduler is not None,
        "balance": {},
        "holdings": [],
    }

    if _scheduler and _scheduler.client:
        result["balance"] = await _get_cached_balance()
        result["holdings"] = await _get_cached_holdings()

    return result


@router.get("/settings")
async def get_settings():
    """전체 설정값"""
    return await repo.get_all_settings()


@router.post("/settings/{key}")
async def update_setting(key: str, value: str):
    """설정값 변경"""
    allowed = {
        "mode": lambda v: v in ("dry", "live"),
        "donchian_period": lambda v: v.isdigit() and 5 <= int(v) <= 100,
        "atr_multiplier": lambda v: _is_float(v) and 1.0 <= float(v) <= 10.0,
        "max_stocks": lambda v: v.isdigit() and 1 <= int(v) <= 20,
        "capital_ratio": lambda v: v.isdigit() and 10 <= int(v) <= 100,
    }

    if key not in allowed:
        return {"error": f"변경 불가: {key}"}
    if not allowed[key](value):
        return {"error": f"잘못된 값: {value}"}

    await repo.set_setting(key, value)
    return {"ok": True, "key": key, "value": value}


@router.post("/control/{action}")
async def control(action: str):
    """매매 제어: start, stop"""
    if action == "stop":
        await repo.set_setting("trading_paused", "1")
        return {"ok": True, "action": "매매 중단"}
    elif action == "start":
        await repo.set_setting("trading_paused", "0")
        return {"ok": True, "action": "매매 재개"}
    return {"error": f"알 수 없는 액션: {action}"}


@router.get("/trades")
async def get_trades():
    """오늘 매매 내역"""
    trades = await repo.get_today_trades()
    return {"trades": trades, "count": len(trades)}


@router.get("/positions")
async def get_positions():
    """현재 포지션"""
    positions = await repo.get_positions()
    return {"positions": positions, "count": len(positions)}


@router.get("/logs")
async def get_logs(lines: int = 50):
    """최근 로그"""
    try:
        with open("data/turtle.log", "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            return {"logs": all_lines[-lines:]}
    except FileNotFoundError:
        return {"logs": []}


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
