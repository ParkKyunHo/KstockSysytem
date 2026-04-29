"""KRX stocks 마스터 seed 스크립트 (pykrx + DB upsert).

stocks 테이블이 비어 있으면 종목 검색 결과가 0건이라 박스 등록이 불가능하므로
이 스크립트로 KOSPI + KOSDAQ 전종목 마스터를 한 번 채운다.

사용법:
    1. .env 에 KRX_ID + KRX_PW (KRX 정보데이터시스템 회원 계정)
    2. python scripts/seed_stocks.py
    3. seed 후 .env 에서 KRX_ID/KRX_PW 라인 제거 권장
       (hotfix 배포 시 server shared/.env 로 mirror 되어 서버에 불필요한
        시크릿이 동기화되는 것을 방지)

전제:
    - DATABASE_URL 은 .env 에 있어야 한다 (서버가 사용하는 것과 동일).
    - stocks 테이블 schema 는 PRD V7.1 기준
      (code, name, market, sector, industry, is_listed, is_managed,
       is_warning, is_alert, is_danger, name_normalized, last_updated_at,
       created_at).
    - 일회성 동작. 매일 자동 sync 는 후속 단위
      (옵션 C 키움 ka10099 또는 systemd timer)에서 처리.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------
# .env 로드 (python-dotenv 가 따옴표/공백/주석 처리 다 해줌)
# ---------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv  # noqa: WPS433
except ImportError:
    print("ERROR: python-dotenv not installed", file=sys.stderr)
    sys.exit(1)
load_dotenv(ROOT / ".env")

if not os.environ.get("KRX_ID") or not os.environ.get("KRX_PW"):
    print("ERROR: KRX_ID / KRX_PW not set in .env", file=sys.stderr)
    sys.exit(1)
if not os.environ.get("DATABASE_URL"):
    print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------
# pykrx + psycopg
# ---------------------------------------------------------------------
import psycopg  # noqa: E402
from pykrx import stock  # noqa: E402


def latest_business_day() -> str:
    """오늘부터 8일 전까지 거슬러 가며 KOSPI ticker 가 있는 첫 날 반환."""
    for delta in range(0, 9):
        d = (datetime.today() - timedelta(days=delta)).strftime("%Y%m%d")
        tickers = stock.get_market_ticker_list(date=d, market="KOSPI")
        if len(tickers) > 0:
            return d
    raise RuntimeError("No business day with KOSPI data in last 9 days")


def fetch_supervision_codes(biz_day: str) -> set[str]:
    """관리종목 코드 set. pykrx 가 fail 하면 빈 set 반환 (graceful)."""
    try:
        rows = stock.get_market_supervision(biz_day)
        # rows: DataFrame with index = ticker, column "지정사유" 등
        return set(rows.index)
    except Exception as exc:  # noqa: BLE001
        print(f"warning: supervision fetch failed: {type(exc).__name__}: {exc}")
        return set()


def main() -> None:
    biz_day = latest_business_day()
    print(f"[1/4] reference business day: {biz_day}")

    managed = fetch_supervision_codes(biz_day)
    print(f"[1/4] managed (관리) stocks: {len(managed)}")

    rows: list[tuple[str, str, str, bool]] = []  # (code, name, market, is_managed)
    for market in ("KOSPI", "KOSDAQ"):
        tickers = stock.get_market_ticker_list(date=biz_day, market=market)
        print(f"[2/4] {market}: {len(tickers)} tickers; fetching names...")
        for i, ticker in enumerate(tickers, 1):
            name = stock.get_market_ticker_name(ticker)
            rows.append((ticker, name, market, ticker in managed))
            if i % 200 == 0:
                print(f"      {market} progress: {i}/{len(tickers)}")
    print(f"[2/4] total fetched: {len(rows)}")

    db_url = (
        os.environ["DATABASE_URL"]
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("+asyncpg", "")
    )

    print("[3/4] DB upsert ...")
    inserted = 0
    updated = 0
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        for code, name, market, is_managed in rows:
            name_norm = name.replace(" ", "").lower()
            cur.execute(
                """
                INSERT INTO stocks (
                    code, name, market, is_listed, is_managed,
                    is_warning, is_alert, is_danger,
                    name_normalized, created_at, last_updated_at
                )
                VALUES (%s, %s, %s, true, %s, false, false, false, %s, now(), now())
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    market = EXCLUDED.market,
                    is_listed = EXCLUDED.is_listed,
                    is_managed = EXCLUDED.is_managed,
                    name_normalized = EXCLUDED.name_normalized,
                    last_updated_at = now()
                RETURNING (xmax = 0) AS inserted
                """,
                (code, name, market, is_managed, name_norm),
            )
            r = cur.fetchone()
            if r and r[0]:
                inserted += 1
            else:
                updated += 1
        conn.commit()

    print(f"[4/4] done: inserted={inserted}, updated={updated}, total={len(rows)}")
    print()
    print("RECOMMEND: remove KRX_ID / KRX_PW lines from .env now (one-time use).")


if __name__ == "__main__":
    main()
