# -*- coding: utf-8 -*-
"""
데이터 로더 모듈
V6.2-Q

3분봉 엑셀 데이터 로딩 및 컬럼 표준화
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
import re

from .config import (
    DATA_DIR,
    COLUMN_MAPPING_ISO,
    COLUMN_MAPPING_POSITIONAL,
    DEFAULT_CONFIG,
)

logger = logging.getLogger(__name__)


def extract_stock_name(filename: str) -> str:
    """파일명에서 종목명 추출

    Args:
        filename: 파일명 (예: "삼성전자(3m).xls", "한미반도체3m.xls")

    Returns:
        종목명 (예: "삼성전자", "한미반도체")
    """
    name = Path(filename).stem
    # (3m) 또는 3m 제거
    name = re.sub(r'\(3m\)$', '', name)
    name = re.sub(r'3m$', '', name)
    return name.strip()


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼명 표준화

    인코딩 문제로 깨진 컬럼명을 표준 컬럼명으로 변환

    Args:
        df: 원본 DataFrame

    Returns:
        표준화된 컬럼명을 가진 DataFrame
    """
    # 먼저 ISO 매핑 시도
    new_columns = []
    for col in df.columns:
        if col in COLUMN_MAPPING_ISO:
            new_columns.append(COLUMN_MAPPING_ISO[col])
        elif col.lower() in ['bandhigh', 'bandlow', 'lowest']:
            new_columns.append(col.lower().replace('bandhigh', 'band_high').replace('bandlow', 'band_low'))
        else:
            new_columns.append(col)

    # 매핑 실패 시 위치 기반 매핑 사용
    if len(new_columns) == len(COLUMN_MAPPING_POSITIONAL):
        # 필수 컬럼 확인
        required = {'date', 'time', 'open', 'high', 'low', 'close'}
        if not required.issubset(set(new_columns)):
            logger.info("Using positional column mapping")
            new_columns = COLUMN_MAPPING_POSITIONAL.copy()

    df.columns = new_columns
    return df


def parse_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """날짜/시간 파싱

    Args:
        df: date, time 컬럼이 있는 DataFrame

    Returns:
        datetime 컬럼이 추가된 DataFrame
    """
    # 날짜 형식 확인 (2026/01/16 또는 2026-01-16)
    sample_date = str(df['date'].iloc[0])

    if '/' in sample_date:
        date_format = '%Y/%m/%d'
    else:
        date_format = '%Y-%m-%d'

    # datetime 생성
    df['datetime'] = pd.to_datetime(
        df['date'].astype(str) + ' ' + df['time'].astype(str),
        format=f'{date_format} %H:%M:%S'
    )

    # date_only 컬럼 (일봉 집계용)
    df['date_only'] = df['datetime'].dt.date

    return df


def filter_regular_hours(df: pd.DataFrame, config=None) -> pd.DataFrame:
    """정규장 시간 필터링

    Args:
        df: datetime 컬럼이 있는 DataFrame
        config: AnalysisConfig 인스턴스

    Returns:
        정규장 시간대만 포함된 DataFrame
    """
    if config is None:
        config = DEFAULT_CONFIG

    # 시간 추출
    df['time_only'] = df['datetime'].dt.time

    # 정규장 시간 파싱
    market_open = pd.to_datetime(config.market_open).time()
    market_close = pd.to_datetime(config.market_close).time()

    # 필터링
    mask = (df['time_only'] >= market_open) & (df['time_only'] <= market_close)
    filtered = df[mask].copy()

    logger.debug(f"Filtered {len(df)} -> {len(filtered)} rows (regular hours)")

    return filtered


def load_single_file(filepath: Path) -> Optional[pd.DataFrame]:
    """단일 엑셀 파일 로드

    Args:
        filepath: 엑셀 파일 경로

    Returns:
        로드된 DataFrame 또는 None (실패 시)
    """
    try:
        # xlrd 엔진 사용 (.xls 파일)
        df = pd.read_excel(filepath, engine='xlrd')

        # 컬럼 표준화
        df = standardize_columns(df)

        # 종목명 추가
        df['stock_name'] = extract_stock_name(filepath.name)

        # datetime 파싱
        df = parse_datetime(df)

        # 정규장 필터링
        df = filter_regular_hours(df)

        # 시간순 정렬 (오름차순)
        df = df.sort_values('datetime').reset_index(drop=True)

        logger.info(f"Loaded {filepath.name}: {len(df)} rows")
        return df

    except Exception as e:
        logger.error(f"Failed to load {filepath}: {e}")
        return None


def load_all_data(data_dir: Path = None) -> Dict[str, pd.DataFrame]:
    """모든 3분봉 데이터 로드

    Args:
        data_dir: 데이터 디렉토리 (기본: 3m_data)

    Returns:
        {종목명: DataFrame} 딕셔너리
    """
    if data_dir is None:
        data_dir = DATA_DIR

    data_dict = {}
    xls_files = list(data_dir.glob("*.xls"))

    logger.info(f"Found {len(xls_files)} .xls files in {data_dir}")

    for filepath in xls_files:
        df = load_single_file(filepath)
        if df is not None:
            stock_name = extract_stock_name(filepath.name)
            data_dict[stock_name] = df

    logger.info(f"Successfully loaded {len(data_dict)} stocks")
    return data_dict


def merge_all_data(data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """모든 종목 데이터 병합

    Args:
        data_dict: {종목명: DataFrame} 딕셔너리

    Returns:
        병합된 단일 DataFrame
    """
    if not data_dict:
        return pd.DataFrame()

    merged = pd.concat(data_dict.values(), ignore_index=True)
    merged = merged.sort_values(['stock_name', 'datetime']).reset_index(drop=True)

    logger.info(f"Merged {len(data_dict)} stocks: {len(merged)} total rows")
    return merged


def get_date_range(df: pd.DataFrame) -> Tuple[str, str]:
    """데이터의 날짜 범위 반환

    Args:
        df: datetime 컬럼이 있는 DataFrame

    Returns:
        (시작일, 종료일) 튜플
    """
    min_date = df['datetime'].min().strftime('%Y-%m-%d')
    max_date = df['datetime'].max().strftime('%Y-%m-%d')
    return min_date, max_date


def get_stock_summary(data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """종목별 데이터 요약

    Args:
        data_dict: {종목명: DataFrame} 딕셔너리

    Returns:
        종목별 요약 DataFrame
    """
    summaries = []
    for stock_name, df in data_dict.items():
        start_date, end_date = get_date_range(df)
        unique_dates = df['date_only'].nunique()

        summaries.append({
            'stock_name': stock_name,
            'start_date': start_date,
            'end_date': end_date,
            'trading_days': unique_dates,
            'total_bars': len(df),
            'avg_bars_per_day': len(df) / unique_dates if unique_dates > 0 else 0,
        })

    return pd.DataFrame(summaries)
