# -*- coding: utf-8 -*-
"""
개선된 진입 조건 백테스트
- 1000억봉 발생 후 조정 대기
- EMA5/EMA8 지지 확인 후 진입
- 3분봉 청산 로직 동일
"""

import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트로 작업 디렉토리 변경
project_root = Path(__file__).resolve().parent.parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np

from src.api.client import KiwoomAPIClient
from src.api.endpoints.market import MarketAPI


class ImprovedEntryBacktest:
    """개선된 진입 조건 백테스트"""

    def __init__(self):
        self.trades = []
        self.signals = []
        self.no_entry_signals = []  # 진입 조건 미충족 신호

    async def find_high_volume_stocks(self, market_api, stocks, limit=None):
        """거래대금 1000억 이상 종목 찾기 (최근 20일 데이터)"""
        high_volume = []
        check_count = limit or len(stocks)

        for i, stock in enumerate(stocks[:check_count]):
            code = stock['code']
            name = stock['name']

            try:
                # 20일치 일봉 데이터 조회
                candles = await market_api.get_daily_chart(stock_code=code, count=20)
                if candles:
                    for c in candles:
                        tv = c.trading_value if hasattr(c, 'trading_value') else c.volume * c.close_price
                        if tv >= 100_000_000_000:  # 1000억
                            candle_date = c.date if isinstance(c.date, date) else (
                                c.date.date() if hasattr(c.date, 'date') else datetime.strptime(str(c.date), '%Y%m%d').date()
                            )
                            high_volume.append({
                                'code': code,
                                'name': name,
                                'date': candle_date,
                                'open': c.open_price,
                                'high': c.high_price,
                                'low': c.low_price,
                                'close': c.close_price,
                                'volume': c.volume,
                                'trading_value': tv
                            })
            except Exception as e:
                pass

            if (i + 1) % 20 == 0:
                print(f'[일봉 조회] {i+1}/{check_count} 종목 완료...')

            await asyncio.sleep(0.12)

        return high_volume

    async def get_daily_candles_after_signal(self, market_api, stock_code, count=30):
        """신호 발생 후 일봉 데이터 조회"""
        try:
            candles = await market_api.get_daily_chart(stock_code=stock_code, count=count)
            if not candles:
                return None

            data = []
            for c in candles:
                candle_date = c.date if isinstance(c.date, date) else (
                    c.date.date() if hasattr(c.date, 'date') else datetime.strptime(str(c.date), '%Y%m%d').date()
                )
                data.append({
                    'date': candle_date,
                    'open': c.open_price,
                    'high': c.high_price,
                    'low': c.low_price,
                    'close': c.close_price,
                    'volume': c.volume,
                    'trading_value': c.trading_value if hasattr(c, 'trading_value') else c.volume * c.close_price
                })

            df = pd.DataFrame(data)
            df = df.sort_values('date').reset_index(drop=True)
            return df
        except Exception as e:
            return None

    async def get_3min_candles(self, client, stock_code, base_date=None):
        """3분봉 데이터 조회 (과거 날짜 기준 가능)

        Args:
            client: KiwoomAPIClient
            stock_code: 종목코드
            base_date: 기준일자 (date 객체 또는 'YYYYMMDD' 문자열)
        """
        try:
            CHART_URL = "/api/dostk/chart"
            body = {
                "stk_cd": stock_code.replace("A", ""),
                "tic_scope": "3",  # 3분봉
                "upd_stkpc_tp": "0",
            }

            # base_date 추가
            if base_date:
                if hasattr(base_date, 'strftime'):
                    body["base_dt"] = base_date.strftime('%Y%m%d')
                else:
                    body["base_dt"] = str(base_date)

            # 연속조회로 데이터 수집
            all_responses = await client.paginate(
                url=CHART_URL,
                api_id="ka10080",
                body=body,
                max_pages=10,
            )

            data = []
            for response_data in all_responses:
                # 키움 분봉 API 응답 키: stk_min_pole_chart_qry
                data_list = response_data.get('stk_min_pole_chart_qry', [])
                if not data_list:
                    data_list = response_data.get('output', response_data.get('list', []))
                if isinstance(data_list, dict):
                    data_list = [data_list]

                for item in data_list:
                    try:
                        # 시간 파싱 (cntr_tm: YYYYMMDDHHMMSS 형식)
                        time_str = str(item.get('cntr_tm', item.get('stck_cntg_hour', '')))
                        if len(time_str) >= 14:
                            timestamp = datetime.strptime(time_str[:14], '%Y%m%d%H%M%S')
                        else:
                            continue

                        data.append({
                            'datetime': timestamp,
                            'open': abs(int(float(item.get('open_pric', item.get('stck_oprc', 0))))),
                            'high': abs(int(float(item.get('high_pric', item.get('stck_hgpr', 0))))),
                            'low': abs(int(float(item.get('low_pric', item.get('stck_lwpr', 0))))),
                            'close': abs(int(float(item.get('cur_prc', item.get('stck_prpr', 0))))),
                            'volume': int(float(item.get('trde_qty', item.get('cntg_vol', 0))))
                        })
                    except Exception:
                        continue

            if not data:
                return None

            df = pd.DataFrame(data)
            df = df.sort_values('datetime').reset_index(drop=True)
            return df
        except Exception as e:
            return None

    def calculate_daily_indicators(self, df):
        """일봉 지표 계산"""
        df = df.copy()
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema8'] = df['close'].ewm(span=8, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['is_bullish'] = df['close'] > df['open']  # 양봉
        df['vol_increase'] = df['volume'] > df['volume'].shift(1)  # 거래량 증가
        return df

    def calculate_3min_indicators(self, df):
        """3분봉 지표 계산"""
        df = df.copy()
        df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema8'] = df['close'].ewm(span=8, adjust=False).mean()
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()

        # ATR
        high = df['high']
        low = df['low']
        close = df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr10'] = tr.ewm(span=10, adjust=False).mean()

        # HLC3
        df['hlc3'] = (df['high'] + df['low'] + df['close']) / 3

        return df

    def find_entry_signal(self, daily_df, signal_date, signal_info):
        """
        개선된 진입 조건 확인
        - 1000억봉 이후 3~10일 내
        - EMA5 또는 EMA8 근처 (±2% 이내)
        - 양봉 + 거래량 증가
        """
        daily_df = self.calculate_daily_indicators(daily_df)

        # 날짜 타입 통일 (date로 변환)
        daily_df['date_only'] = daily_df['date'].apply(
            lambda x: x.date() if hasattr(x, 'date') else x
        )
        if hasattr(signal_date, 'date'):
            signal_date = signal_date.date()

        # 1000억봉 인덱스 찾기
        signal_idx = daily_df[daily_df['date_only'] == signal_date].index
        if len(signal_idx) == 0:
            return None
        signal_idx = signal_idx[0]

        # 1000억봉 이후 데이터
        post_signal = daily_df[daily_df.index > signal_idx].copy()

        if len(post_signal) < 2:
            return None

        # 3~14일 내에서 진입 신호 탐색 (2주)
        for idx in range(min(2, len(post_signal)), min(14, len(post_signal))):
            row = post_signal.iloc[idx]
            close = row['close']
            low = row['low']
            ema5 = row['ema5']
            ema8 = row['ema8']

            # 조건 1: EMA8 근처만 확인 (저점이 ±2% 이내)
            ema8_diff = abs(low - ema8) / ema8 * 100 if ema8 > 0 else 100
            near_ema8 = ema8_diff <= 2.0

            if not near_ema8:
                continue

            # 조건 2: 양봉
            is_bullish = row['is_bullish']
            if not is_bullish:
                continue

            # 조건 3: 거래량 증가 (옵션 - 완화된 조건)
            # vol_increase = row['vol_increase']

            # 조건 4: 종가가 EMA8 위
            above_ema = close >= ema8
            if not above_ema:
                continue

            # 진입 신호 발견 (EMA8 고정)
            return {
                'entry_date': row['date'],
                'entry_price': int(close),
                'touched_ema': 'EMA8',
                'ema5': int(ema5),
                'ema8': int(ema8),
                'days_after_signal': idx + 1,
                'entry_idx': post_signal.index[idx]
            }

        return None

    def simulate_3min_exit(self, minute_df, entry_price, stock_info, entry_info):
        """3분봉 청산 시뮬레이션"""
        if minute_df is None or len(minute_df) < 100:
            return None

        minute_df = self.calculate_3min_indicators(minute_df)

        # 진입일 기준으로 데이터 필터링
        entry_date = entry_info['entry_date']
        if hasattr(entry_date, 'date'):
            entry_date_only = entry_date.date()
        else:
            entry_date_only = pd.to_datetime(entry_date).date()

        # 진입일 이후 데이터만 사용
        minute_df['date_only'] = minute_df['datetime'].dt.date
        post_entry = minute_df[minute_df['date_only'] >= entry_date_only].copy()

        if len(post_entry) < 50:
            return None

        # 지표 안정화를 위해 첫 20봉 스킵
        entry_idx = 20

        # 청산 시뮬레이션
        stop_price = entry_price * 0.96  # -4% 고정 손절
        trailing_stop = None
        highest_close = entry_price
        highest_price = entry_price
        structure_warning_count = 0
        atr_mult = 6.0

        entry_datetime = post_entry.iloc[entry_idx]['datetime']
        minute_df = post_entry  # 이후 로직에서 post_entry 사용

        for i in range(entry_idx, len(minute_df)):
            row = minute_df.iloc[i]
            bar_datetime = row['datetime']
            bar_high = row['high']
            bar_low = row['low']
            bar_close = row['close']
            hlc3 = row['hlc3']
            ema9 = row['ema9']
            atr = row['atr10']

            # 최고가 업데이트
            highest_close = max(highest_close, bar_close)
            highest_price = max(highest_price, bar_high)

            # 1. 고정 손절 (-4%)
            if bar_low <= stop_price:
                exit_price = int(stop_price)
                pnl_pct = -4.0
                return self._create_trade_result(
                    stock_info, entry_info, entry_datetime, entry_price,
                    bar_datetime, exit_price, 'HARD_STOP_4%',
                    i - entry_idx, highest_price, highest_close, trailing_stop, atr_mult, pnl_pct
                )

            # 2. ATR 트레일링 스탑 계산
            if pd.notna(atr) and atr > 0:
                new_ts = hlc3 - atr * atr_mult
                if trailing_stop is None:
                    trailing_stop = new_ts
                else:
                    trailing_stop = max(trailing_stop, new_ts)

            # 3. ATR 트레일링 스탑 체크
            if trailing_stop and bar_close <= trailing_stop:
                exit_price = int(bar_close)
                pnl_pct = round(((bar_close - entry_price) / entry_price) * 100, 2)
                return self._create_trade_result(
                    stock_info, entry_info, entry_datetime, entry_price,
                    bar_datetime, exit_price, f'ATR_TS_{atr_mult}',
                    i - entry_idx, highest_price, highest_close, trailing_stop, atr_mult, pnl_pct
                )

            # 4. Structure Warning
            if pd.notna(ema9) and hlc3 < ema9:
                structure_warning_count += 1
                if structure_warning_count >= 2:
                    atr_mult = 4.5
            else:
                structure_warning_count = 0

        # 데이터 끝
        last_row = minute_df.iloc[-1]
        exit_price = int(last_row['close'])
        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)

        return self._create_trade_result(
            stock_info, entry_info, entry_datetime, entry_price,
            last_row['datetime'], exit_price, 'DATA_END',
            len(minute_df) - entry_idx, highest_price, highest_close, trailing_stop, atr_mult, pnl_pct
        )

    def _create_trade_result(self, stock_info, entry_info, entry_datetime, entry_price,
                             exit_datetime, exit_price, exit_reason,
                             holding_bars, highest_price, highest_close, trailing_stop, atr_mult, pnl_pct):
        """거래 결과 생성"""
        return {
            'stock_code': stock_info['code'],
            'stock_name': stock_info['name'],
            'signal_date': stock_info['date'],
            'signal_trading_value': stock_info['trading_value'],
            'entry_date': entry_info['entry_date'],
            'entry_price': entry_price,
            'touched_ema': entry_info['touched_ema'],
            'days_after_signal': entry_info['days_after_signal'],
            'entry_datetime': entry_datetime,
            'exit_datetime': exit_datetime,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'holding_bars': holding_bars,
            'highest_price': highest_price,
            'highest_close': highest_close,
            'max_profit_pct': round(((highest_close - entry_price) / entry_price) * 100, 2),
            'trailing_stop_final': int(trailing_stop) if trailing_stop else None,
            'atr_mult_final': atr_mult,
            'pnl_pct': pnl_pct,
            'pnl_amount': int((exit_price - entry_price) * (1000000 / entry_price))
        }

    def analyze_results(self):
        """결과 분석"""
        if not self.trades:
            return {}

        df = pd.DataFrame(self.trades)

        total_trades = len(df)
        wins = df[df['pnl_pct'] > 0]
        losses = df[df['pnl_pct'] <= 0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0

        total_pnl_pct = df['pnl_pct'].sum()
        avg_pnl_pct = df['pnl_pct'].mean()
        median_pnl_pct = df['pnl_pct'].median()
        std_pnl_pct = df['pnl_pct'].std()

        avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl_pct'].mean() if len(losses) > 0 else 0

        max_win = df['pnl_pct'].max()
        max_loss = df['pnl_pct'].min()

        gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        exit_reasons = df['exit_reason'].value_counts().to_dict()
        exit_pnl = df.groupby('exit_reason')['pnl_pct'].agg(['mean', 'sum', 'count']).to_dict('index')

        avg_holding_bars = df['holding_bars'].mean()
        avg_holding_hours = avg_holding_bars * 3 / 60

        df['profit_giveback'] = df['max_profit_pct'] - df['pnl_pct']
        avg_giveback = df['profit_giveback'].mean()

        risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)

        # EMA별 분석
        ema_analysis = df.groupby('touched_ema')['pnl_pct'].agg(['mean', 'sum', 'count']).to_dict('index')

        # 진입 일수별 분석
        days_analysis = df.groupby('days_after_signal')['pnl_pct'].agg(['mean', 'sum', 'count']).to_dict('index')

        return {
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': round(win_rate, 2),
            'total_pnl_pct': round(total_pnl_pct, 2),
            'avg_pnl_pct': round(avg_pnl_pct, 2),
            'median_pnl_pct': round(median_pnl_pct, 2),
            'std_pnl_pct': round(std_pnl_pct, 2),
            'avg_win_pct': round(avg_win, 2),
            'avg_loss_pct': round(avg_loss, 2),
            'max_win_pct': round(max_win, 2),
            'max_loss_pct': round(max_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'risk_reward_ratio': round(risk_reward, 2),
            'expectancy': round(expectancy, 2),
            'avg_holding_bars': round(avg_holding_bars, 1),
            'avg_holding_hours': round(avg_holding_hours, 2),
            'avg_profit_giveback': round(avg_giveback, 2),
            'exit_reasons': exit_reasons,
            'exit_pnl': exit_pnl,
            'ema_analysis': ema_analysis,
            'days_analysis': days_analysis,
            'no_entry_count': len(self.no_entry_signals)
        }

    def save_to_excel(self, output_path):
        """엑셀 저장"""
        if not self.trades:
            print("저장할 거래 데이터가 없습니다.")
            return

        df = pd.DataFrame(self.trades)

        columns_order = [
            'stock_code', 'stock_name', 'signal_date', 'signal_trading_value',
            'entry_date', 'touched_ema', 'days_after_signal',
            'entry_price', 'exit_datetime', 'exit_price',
            'exit_reason', 'holding_bars', 'pnl_pct', 'pnl_amount',
            'highest_price', 'highest_close', 'max_profit_pct',
            'trailing_stop_final', 'atr_mult_final'
        ]

        # 존재하는 컬럼만 선택
        columns_order = [c for c in columns_order if c in df.columns]
        df = df[columns_order]

        df.columns = [
            '종목코드', '종목명', '신호일', '신호거래대금',
            '진입일', '터치EMA', '신호후일수',
            '진입가', '청산시각', '청산가',
            '청산사유', '보유봉수', '수익률%', '손익금액',
            '최고가', '최고종가', '최대수익률%',
            '최종TS', '최종ATR배수'
        ][:len(columns_order)]

        if '신호거래대금' in df.columns:
            df['신호거래대금'] = (df['신호거래대금'] / 100_000_000).round(0).astype(int)

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='거래내역', index=False)

            # 분석 결과
            stats = self.analyze_results()
            stats_df = pd.DataFrame([
                {'항목': '=== 기본 통계 ===', '값': ''},
                {'항목': '총 신호 수', '값': stats['total_trades'] + stats['no_entry_count']},
                {'항목': '진입 성공', '값': stats['total_trades']},
                {'항목': '진입 실패 (조건 미충족)', '값': stats['no_entry_count']},
                {'항목': '', '값': ''},
                {'항목': '총 거래 수', '값': stats['total_trades']},
                {'항목': '승리', '값': stats['win_count']},
                {'항목': '패배', '값': stats['loss_count']},
                {'항목': '승률 (%)', '값': stats['win_rate']},
                {'항목': '', '값': ''},
                {'항목': '=== 수익률 ===', '값': ''},
                {'항목': '총 수익률 (%)', '값': stats['total_pnl_pct']},
                {'항목': '평균 수익률 (%)', '값': stats['avg_pnl_pct']},
                {'항목': '중앙값 수익률 (%)', '값': stats['median_pnl_pct']},
                {'항목': '표준편차 (%)', '값': stats['std_pnl_pct']},
                {'항목': '', '값': ''},
                {'항목': '평균 이익 (%)', '값': stats['avg_win_pct']},
                {'항목': '평균 손실 (%)', '값': stats['avg_loss_pct']},
                {'항목': '최대 이익 (%)', '값': stats['max_win_pct']},
                {'항목': '최대 손실 (%)', '값': stats['max_loss_pct']},
                {'항목': '', '값': ''},
                {'항목': '=== 리스크 지표 ===', '값': ''},
                {'항목': 'Profit Factor', '값': stats['profit_factor']},
                {'항목': 'Risk/Reward Ratio', '값': stats['risk_reward_ratio']},
                {'항목': 'Expectancy (%)', '값': stats['expectancy']},
                {'항목': '', '값': ''},
                {'항목': '=== 보유 분석 ===', '값': ''},
                {'항목': '평균 보유 봉 수', '값': stats['avg_holding_bars']},
                {'항목': '평균 보유 시간 (시간)', '값': stats['avg_holding_hours']},
                {'항목': '평균 이익 반납률 (%)', '값': stats['avg_profit_giveback']},
            ])
            stats_df.to_excel(writer, sheet_name='분석결과', index=False)

            # 청산유형별 분석
            exit_analysis = []
            for reason, data in stats['exit_pnl'].items():
                exit_analysis.append({
                    '청산유형': reason,
                    '건수': int(data['count']),
                    '평균수익률%': round(data['mean'], 2),
                    '총수익률%': round(data['sum'], 2)
                })
            exit_df = pd.DataFrame(exit_analysis)
            exit_df.to_excel(writer, sheet_name='청산유형분석', index=False)

            # EMA별 분석
            ema_analysis = []
            for ema, data in stats['ema_analysis'].items():
                ema_analysis.append({
                    'EMA': ema,
                    '건수': int(data['count']),
                    '평균수익률%': round(data['mean'], 2),
                    '총수익률%': round(data['sum'], 2)
                })
            ema_df = pd.DataFrame(ema_analysis)
            ema_df.to_excel(writer, sheet_name='EMA별분석', index=False)

            # 진입일수별 분석
            days_analysis = []
            for days, data in stats['days_analysis'].items():
                days_analysis.append({
                    '신호후일수': int(days),
                    '건수': int(data['count']),
                    '평균수익률%': round(data['mean'], 2),
                    '총수익률%': round(data['sum'], 2)
                })
            days_df = pd.DataFrame(days_analysis)
            days_df = days_df.sort_values('신호후일수')
            days_df.to_excel(writer, sheet_name='진입일수별분석', index=False)

            # 진입 실패 종목
            if self.no_entry_signals:
                no_entry_df = pd.DataFrame(self.no_entry_signals)
                no_entry_df['trading_value'] = (no_entry_df['trading_value'] / 100_000_000).round(0).astype(int)
                no_entry_df.columns = ['종목코드', '종목명', '신호일', '신호가', '거래대금억', '실패사유']
                no_entry_df.to_excel(writer, sheet_name='진입실패종목', index=False)

        print(f'\n결과 저장 완료: {output_path}')


async def run_improved_backtest():
    """개선된 진입 조건 백테스트 실행"""
    print('=' * 70)
    print('  개선된 진입 조건 백테스트')
    print('  전략: 1000억봉 -> EMA5/EMA8 지지 확인 -> 진입')
    print('=' * 70)

    # past1000.csv에서 종목 목록 읽기
    csv_path = project_root / 'past1000.csv'
    df = pd.read_csv(csv_path, encoding='cp949', dtype=str)

    etf_keywords = ['KODEX', 'TIGER', 'RISE', 'SOL', 'HANARO', 'PLUS', 'KBSTAR', 'ACE', 'ARIRANG', 'KOSEF', 'ETF', 'ETN']

    stocks = []
    for _, row in df.iterrows():
        code = str(row.iloc[0]).replace("'", '').strip()
        name = str(row.iloc[1]).strip() if len(row) > 1 else ''
        if len(code) == 6 and not any(kw in name for kw in etf_keywords):
            stocks.append({'code': code, 'name': name})

    print(f'총 {len(stocks)}개 종목 (ETF 제외)')

    # 테스트 종목 수 제한 (디버깅용)
    TEST_LIMIT = None  # None이면 전체, 숫자면 해당 개수만
    if TEST_LIMIT:
        stocks = stocks[:TEST_LIMIT]
        print(f'[DEBUG] 테스트 제한: {TEST_LIMIT}개 종목만 테스트')

    runner = ImprovedEntryBacktest()
    client = KiwoomAPIClient()

    async with client:
        market_api = MarketAPI(client)

        # Step 1: 각 종목의 일봉에서 1000억봉 + 10% 상승 찾기
        print('\n[Step 1] 거래대금 1000억 + 등락률 10% 이상 봉 탐색...')
        unique_signals = []

        for i, stock in enumerate(stocks):
            code = stock['code']
            name = stock['name']

            # 60일치 일봉 조회
            daily_df = await runner.get_daily_candles_after_signal(market_api, code, count=60)

            if daily_df is None or len(daily_df) < 20:
                continue

            # 거래대금 1000억 이상 + 등락률 10% 이상인 날 찾기
            for idx, row in daily_df.iterrows():
                tv = row.get('trading_value', row['volume'] * row['close'])
                change_pct = ((row['close'] - row['open']) / row['open']) * 100 if row['open'] > 0 else 0

                if tv >= 100_000_000_000 and change_pct >= 10.0:  # 1000억 + 10% 이상 상승
                    signal_date = row['date']
                    if hasattr(signal_date, 'date'):
                        signal_date = signal_date.date()

                    unique_signals.append({
                        'code': code,
                        'name': name,
                        'date': signal_date,
                        'trading_value': tv,
                        'change_pct': round(change_pct, 2),
                        'close': int(row['close']),
                        'daily_df': daily_df  # 일봉 데이터 재사용
                    })

            if (i + 1) % 10 == 0:
                print(f'  [{i+1}/{len(stocks)}] 종목 조회 완료...')

            await asyncio.sleep(0.15)

        print(f'\n거래대금 1000억 이상: {len(unique_signals)}건 발견')

        # Step 2: 각 종목별 진입 조건 확인 및 테스트
        print(f'\n[Step 2] {len(unique_signals)}건 개선된 진입 조건 테스트...')

        for i, stock in enumerate(unique_signals):
            code = stock['code']
            name = stock['name']
            daily_df = stock['daily_df']  # 이미 조회한 일봉 데이터 재사용

            print(f'\n[DEBUG] {code} {name}')
            print(f'  기준봉: {stock["date"]} (거래대금: {stock["trading_value"]/100_000_000:.0f}억, 등락률: +{stock.get("change_pct", 0):.1f}%)')
            print(f'  일봉 범위: {daily_df["date"].min()} ~ {daily_df["date"].max()} ({len(daily_df)}개)')

            # 진입 신호 탐색
            entry_info = runner.find_entry_signal(daily_df, stock['date'], stock)
            print(f'  진입 신호: {entry_info}')

            if entry_info is None:
                runner.no_entry_signals.append({
                    'code': code, 'name': name, 'date': stock['date'],
                    'close': stock['close'], 'trading_value': stock['trading_value'],
                    'reason': 'NO_ENTRY_SIGNAL'
                })
                if (i + 1) % 10 == 0:
                    print(f'  [{i+1}/{len(unique_signals)}] {code} {name}: 진입 조건 미충족')
                continue

            # 3분봉 데이터 조회 (진입일 기준)
            minute_df = await runner.get_3min_candles(client, code, entry_info['entry_date'])

            if minute_df is None:
                print(f'  [DEBUG] {code}: 3분봉 데이터 None')
                runner.no_entry_signals.append({
                    'code': code, 'name': name, 'date': stock['date'],
                    'close': stock['close'], 'trading_value': stock['trading_value'],
                    'reason': 'NO_3MIN_DATA'
                })
                continue

            print(f'  [DEBUG] {code}: 3분봉 {len(minute_df)}개, 범위: {minute_df["datetime"].min()} ~ {minute_df["datetime"].max()}')

            if len(minute_df) < 100:
                runner.no_entry_signals.append({
                    'code': code, 'name': name, 'date': stock['date'],
                    'close': stock['close'], 'trading_value': stock['trading_value'],
                    'reason': 'NO_3MIN_DATA'
                })
                continue

            # 청산 시뮬레이션
            result = runner.simulate_3min_exit(minute_df, entry_info['entry_price'], stock, entry_info)

            if result is None:
                print(f'  [DEBUG] {code}: 청산 시뮬레이션 결과 None')
                continue

            if result:
                runner.trades.append(result)
                status = 'WIN' if result['pnl_pct'] > 0 else 'LOSS'
                print(f"  [{i+1}/{len(unique_signals)}] [{status}] {code} {name}: {entry_info['touched_ema']} D+{entry_info['days_after_signal']} -> {result['pnl_pct']:+.2f}% ({result['exit_reason']})")

            await asyncio.sleep(0.5)

        # Step 3: 결과 분석
        print('\n' + '=' * 70)
        print('  백테스트 결과 분석 (개선된 진입 조건)')
        print('=' * 70)

        stats = runner.analyze_results()

        if stats:
            print(f'''
┌─────────────────────────────────────────────────────────────────────┐
│  신호 통계                                                          │
├─────────────────────────────────────────────────────────────────────┤
│  총 신호 수: {stats['total_trades'] + stats['no_entry_count']:>5}건                                              │
│  진입 성공: {stats['total_trades']:>5}건 | 진입 실패: {stats['no_entry_count']:>5}건                              │
├─────────────────────────────────────────────────────────────────────┤
│  기본 통계                                                          │
├─────────────────────────────────────────────────────────────────────┤
│  총 거래 수: {stats['total_trades']:>5}건                                              │
│  승/패: {stats['win_count']}/{stats['loss_count']} (승률: {stats['win_rate']:.1f}%)                                       │
├─────────────────────────────────────────────────────────────────────┤
│  수익률 분석                                                        │
├─────────────────────────────────────────────────────────────────────┤
│  총 수익률: {stats['total_pnl_pct']:>+8.2f}%                                           │
│  평균 수익률: {stats['avg_pnl_pct']:>+7.2f}% (중앙값: {stats['median_pnl_pct']:>+6.2f}%)                       │
│  표준편차: {stats['std_pnl_pct']:>7.2f}%                                              │
│  평균 이익: {stats['avg_win_pct']:>+7.2f}% | 평균 손실: {stats['avg_loss_pct']:>+7.2f}%                     │
│  최대 이익: {stats['max_win_pct']:>+7.2f}% | 최대 손실: {stats['max_loss_pct']:>+7.2f}%                     │
├─────────────────────────────────────────────────────────────────────┤
│  리스크 지표                                                        │
├─────────────────────────────────────────────────────────────────────┤
│  Profit Factor: {stats['profit_factor']:>6.2f}                                          │
│  Risk/Reward Ratio: {stats['risk_reward_ratio']:>5.2f}                                       │
│  Expectancy: {stats['expectancy']:>+6.2f}%                                            │
├─────────────────────────────────────────────────────────────────────┤
│  보유 분석                                                          │
├─────────────────────────────────────────────────────────────────────┤
│  평균 보유: {stats['avg_holding_bars']:>6.1f}봉 ({stats['avg_holding_hours']:>5.1f}시간)                               │
│  평균 이익 반납률: {stats['avg_profit_giveback']:>5.2f}%                                      │
└─────────────────────────────────────────────────────────────────────┘
''')

            print('\n[청산 유형별 분석]')
            print('-' * 50)
            for reason, data in stats['exit_pnl'].items():
                print(f"  {reason:20}: {int(data['count']):>3}건 | 평균: {data['mean']:>+6.2f}% | 합계: {data['sum']:>+7.2f}%")

            print('\n[터치 EMA별 분석]')
            print('-' * 50)
            for ema, data in stats['ema_analysis'].items():
                print(f"  {ema:20}: {int(data['count']):>3}건 | 평균: {data['mean']:>+6.2f}% | 합계: {data['sum']:>+7.2f}%")

            print('\n[신호 후 진입일수별 분석]')
            print('-' * 50)
            for days, data in sorted(stats['days_analysis'].items()):
                print(f"  D+{days:<3}: {int(data['count']):>3}건 | 평균: {data['mean']:>+6.2f}% | 합계: {data['sum']:>+7.2f}%")

        # Step 4: 엑셀 저장
        output_path = project_root / 'improved_entry_backtest_result_v2.xlsx'
        runner.save_to_excel(output_path)

        # 1차 테스트 결과와 비교
        print('\n' + '=' * 70)
        print('  1차 테스트 결과와 비교')
        print('=' * 70)
        print('''
┌──────────────────────┬──────────────────┬──────────────────┐
│        항목          │   1차 테스트     │  개선된 진입     │
├──────────────────────┼──────────────────┼──────────────────┤
│  진입 조건           │ 1000억봉 다음날  │ EMA5/8 지지 확인 │
│  총 거래             │      106건       │      ???건       │
│  승률                │      18.9%       │      ???%        │
│  Profit Factor       │       0.51       │      ???         │
│  총 수익률           │    -155.46%      │      ???%        │
└──────────────────────┴──────────────────┴──────────────────┘
''')

        print('\n백테스트 완료!')


if __name__ == '__main__':
    asyncio.run(run_improved_backtest())
