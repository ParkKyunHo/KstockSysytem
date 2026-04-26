# -*- coding: utf-8 -*-
"""
결과 내보내기 모듈
V6.2-Q

분석 결과를 CSV, Excel로 저장
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import logging
import json

from .config import OUTPUT_DIR

logger = logging.getLogger(__name__)


class ResultExporter:
    """분석 결과 내보내기"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_all(
        self,
        daily_events: pd.DataFrame,
        event_summary: pd.DataFrame,
        time_distribution_result,
        band_breakout_result,
        price_pattern_result,
        indicator_validity_result,
        volume_pattern_result,
        holding_period_result,
        entry_timing_result,
    ) -> Dict[str, Path]:
        """모든 분석 결과 내보내기

        Returns:
            생성된 파일 경로 딕셔너리
        """
        exported_files = {}

        # 1. 이벤트 발생일 목록
        if daily_events is not None and not daily_events.empty:
            path = self._save_csv(daily_events, 'daily_events.csv')
            exported_files['daily_events'] = path

        # 2. 이벤트 요약
        if event_summary is not None and not event_summary.empty:
            path = self._save_csv(event_summary, 'event_summary.csv')
            exported_files['event_summary'] = path

        # 3. 시간대별 분석
        if time_distribution_result:
            exported_files.update(self._export_time_distribution(time_distribution_result))

        # 4. 밴드 돌파 분석
        if band_breakout_result:
            exported_files.update(self._export_band_breakout(band_breakout_result))

        # 5. 가격 패턴 분석
        if price_pattern_result:
            exported_files.update(self._export_price_pattern(price_pattern_result))

        # 6. 지표 유효성 분석
        if indicator_validity_result:
            exported_files.update(self._export_indicator_validity(indicator_validity_result))

        # 7. 거래량 패턴 분석
        if volume_pattern_result:
            exported_files.update(self._export_volume_pattern(volume_pattern_result))

        # 8. 보유 시간 분석
        if holding_period_result:
            exported_files.update(self._export_holding_period(holding_period_result))

        # 9. 진입 타이밍 분석
        if entry_timing_result:
            exported_files.update(self._export_entry_timing(entry_timing_result))

        # 10. 종합 보고서 (Excel)
        summary_path = self._create_summary_report(
            daily_events, event_summary,
            time_distribution_result, band_breakout_result,
            price_pattern_result, indicator_validity_result,
            volume_pattern_result, holding_period_result,
            entry_timing_result
        )
        exported_files['summary_report'] = summary_path

        logger.info(f"Exported {len(exported_files)} files to {self.output_dir}")
        return exported_files

    def _save_csv(self, df: pd.DataFrame, filename: str) -> Path:
        """DataFrame을 CSV로 저장"""
        path = self.output_dir / filename
        df.to_csv(path, index=False, encoding='utf-8-sig')
        logger.debug(f"Saved {filename}")
        return path

    def _save_json(self, data: Dict, filename: str) -> Path:
        """딕셔너리를 JSON으로 저장"""
        path = self.output_dir / filename

        def convert(obj):
            if isinstance(obj, (np.integer, np.floating)):
                return float(obj) if np.isfinite(obj) else None
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, pd.DataFrame):
                return obj.to_dict('records')
            if pd.isna(obj):
                return None
            return obj

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, default=convert, ensure_ascii=False, indent=2)

        logger.debug(f"Saved {filename}")
        return path

    def _export_time_distribution(self, result) -> Dict[str, Path]:
        """시간대별 분석 결과 내보내기"""
        exported = {}

        if hasattr(result, 'bucket_stats') and isinstance(result.bucket_stats, pd.DataFrame) and not result.bucket_stats.empty:
            path = self._save_csv(result.bucket_stats, 'time_distribution_buckets.csv')
            exported['time_distribution_buckets'] = path

        if hasattr(result, 'peak_times') and isinstance(result.peak_times, pd.DataFrame) and not result.peak_times.empty:
            path = self._save_csv(result.peak_times, 'time_distribution_peaks.csv')
            exported['time_distribution_peaks'] = path

        if hasattr(result, 'pattern_classification') and isinstance(result.pattern_classification, dict):
            if 'details' in result.pattern_classification and isinstance(result.pattern_classification['details'], pd.DataFrame):
                if not result.pattern_classification['details'].empty:
                    path = self._save_csv(result.pattern_classification['details'], 'time_distribution_patterns.csv')
                    exported['time_distribution_patterns'] = path

        return exported

    def _export_band_breakout(self, result) -> Dict[str, Path]:
        """밴드 돌파 분석 결과 내보내기"""
        exported = {}

        if hasattr(result, 'first_breakout_stats') and isinstance(result.first_breakout_stats, dict):
            if 'raw_data' in result.first_breakout_stats and isinstance(result.first_breakout_stats['raw_data'], pd.DataFrame):
                if not result.first_breakout_stats['raw_data'].empty:
                    path = self._save_csv(result.first_breakout_stats['raw_data'], 'band_breakout_first.csv')
                    exported['band_breakout_first'] = path

        if hasattr(result, 'post_breakout_returns') and isinstance(result.post_breakout_returns, dict):
            if 'summary' in result.post_breakout_returns and isinstance(result.post_breakout_returns['summary'], pd.DataFrame):
                if not result.post_breakout_returns['summary'].empty:
                    path = self._save_csv(result.post_breakout_returns['summary'], 'band_breakout_returns.csv')
                    exported['band_breakout_returns'] = path

        if hasattr(result, 'bandlow_analysis') and isinstance(result.bandlow_analysis, dict):
            if 'pattern_stats' in result.bandlow_analysis and isinstance(result.bandlow_analysis['pattern_stats'], pd.DataFrame):
                if not result.bandlow_analysis['pattern_stats'].empty:
                    path = self._save_csv(result.bandlow_analysis['pattern_stats'], 'bandlow_patterns.csv')
                    exported['bandlow_patterns'] = path

        return exported

    def _export_price_pattern(self, result) -> Dict[str, Path]:
        """가격 패턴 분석 결과 내보내기"""
        exported = {}

        if hasattr(result, 'high_low_timing') and isinstance(result.high_low_timing, dict):
            if 'raw_data' in result.high_low_timing and isinstance(result.high_low_timing['raw_data'], pd.DataFrame):
                if not result.high_low_timing['raw_data'].empty:
                    path = self._save_csv(result.high_low_timing['raw_data'], 'price_high_low_timing.csv')
                    exported['price_high_low_timing'] = path

        if hasattr(result, 'high_to_close') and isinstance(result.high_to_close, dict):
            if 'raw_data' in result.high_to_close and isinstance(result.high_to_close['raw_data'], pd.DataFrame):
                if not result.high_to_close['raw_data'].empty:
                    path = self._save_csv(result.high_to_close['raw_data'], 'price_high_to_close.csv')
                    exported['price_high_to_close'] = path

        if hasattr(result, 'mfe_mae') and isinstance(result.mfe_mae, dict):
            if 'raw_data' in result.mfe_mae and isinstance(result.mfe_mae['raw_data'], pd.DataFrame):
                if not result.mfe_mae['raw_data'].empty:
                    path = self._save_csv(result.mfe_mae['raw_data'], 'price_mfe_mae.csv')
                    exported['price_mfe_mae'] = path

        return exported

    def _export_indicator_validity(self, result) -> Dict[str, Path]:
        """지표 유효성 분석 결과 내보내기"""
        exported = {}

        if hasattr(result, 'ema_divergence') and isinstance(result.ema_divergence, dict):
            if 'bucket_stats' in result.ema_divergence and isinstance(result.ema_divergence['bucket_stats'], pd.DataFrame):
                if not result.ema_divergence['bucket_stats'].empty:
                    path = self._save_csv(result.ema_divergence['bucket_stats'], 'indicator_ema_divergence.csv')
                    exported['indicator_ema_divergence'] = path

        if hasattr(result, 'stop_loss_validity') and isinstance(result.stop_loss_validity, dict):
            if 'result_stats' in result.stop_loss_validity and isinstance(result.stop_loss_validity['result_stats'], pd.DataFrame):
                if not result.stop_loss_validity['result_stats'].empty:
                    path = self._save_csv(result.stop_loss_validity['result_stats'], 'indicator_stop_loss.csv')
                    exported['indicator_stop_loss'] = path

        if hasattr(result, 'ceiling_break_validity') and isinstance(result.ceiling_break_validity, dict):
            if 'raw_data' in result.ceiling_break_validity and isinstance(result.ceiling_break_validity['raw_data'], pd.DataFrame):
                if not result.ceiling_break_validity['raw_data'].empty:
                    path = self._save_csv(result.ceiling_break_validity['raw_data'], 'indicator_ceiling_break.csv')
                    exported['indicator_ceiling_break'] = path

        return exported

    def _export_volume_pattern(self, result) -> Dict[str, Path]:
        """거래량 패턴 분석 결과 내보내기"""
        exported = {}

        if hasattr(result, 'surge_analysis') and isinstance(result.surge_analysis, dict):
            if 'hourly_stats' in result.surge_analysis and isinstance(result.surge_analysis['hourly_stats'], pd.DataFrame):
                if not result.surge_analysis['hourly_stats'].empty:
                    path = self._save_csv(result.surge_analysis['hourly_stats'], 'volume_surge_hourly.csv')
                    exported['volume_surge_hourly'] = path

        if hasattr(result, 'distribution_pattern') and isinstance(result.distribution_pattern, dict):
            if 'details' in result.distribution_pattern and isinstance(result.distribution_pattern['details'], pd.DataFrame):
                if not result.distribution_pattern['details'].empty:
                    path = self._save_csv(result.distribution_pattern['details'], 'volume_distribution.csv')
                    exported['volume_distribution'] = path

        if hasattr(result, 'cumulative_curve') and isinstance(result.cumulative_curve, dict):
            if 'curve_stats' in result.cumulative_curve and isinstance(result.cumulative_curve['curve_stats'], pd.DataFrame):
                if not result.cumulative_curve['curve_stats'].empty:
                    path = self._save_csv(result.cumulative_curve['curve_stats'], 'volume_cumulative.csv')
                    exported['volume_cumulative'] = path

        return exported

    def _export_holding_period(self, result) -> Dict[str, Path]:
        """보유 시간 분석 결과 내보내기"""
        exported = {}

        if hasattr(result, 'period_returns') and isinstance(result.period_returns, dict):
            if 'summary' in result.period_returns and isinstance(result.period_returns['summary'], pd.DataFrame):
                if not result.period_returns['summary'].empty:
                    path = self._save_csv(result.period_returns['summary'], 'holding_period_returns.csv')
                    exported['holding_period_returns'] = path

        if hasattr(result, 'entry_time_efficiency') and isinstance(result.entry_time_efficiency, dict):
            if 'summary' in result.entry_time_efficiency and isinstance(result.entry_time_efficiency['summary'], pd.DataFrame):
                if not result.entry_time_efficiency['summary'].empty:
                    path = self._save_csv(result.entry_time_efficiency['summary'], 'holding_entry_efficiency.csv')
                    exported['holding_entry_efficiency'] = path

        if hasattr(result, 'risk_reward_analysis') and isinstance(result.risk_reward_analysis, dict):
            if 'summary' in result.risk_reward_analysis and isinstance(result.risk_reward_analysis['summary'], pd.DataFrame):
                if not result.risk_reward_analysis['summary'].empty:
                    path = self._save_csv(result.risk_reward_analysis['summary'], 'holding_risk_reward.csv')
                    exported['holding_risk_reward'] = path

        return exported

    def _export_entry_timing(self, result) -> Dict[str, Path]:
        """진입 타이밍 분석 결과 내보내기"""
        exported = {}

        if hasattr(result, 'optimal_entry_time') and isinstance(result.optimal_entry_time, dict):
            if 'summary' in result.optimal_entry_time and isinstance(result.optimal_entry_time['summary'], pd.DataFrame):
                if not result.optimal_entry_time['summary'].empty:
                    path = self._save_csv(result.optimal_entry_time['summary'], 'entry_timing_optimal.csv')
                    exported['entry_timing_optimal'] = path

        if hasattr(result, 'stop_loss_effectiveness') and isinstance(result.stop_loss_effectiveness, dict):
            if 'summary' in result.stop_loss_effectiveness and isinstance(result.stop_loss_effectiveness['summary'], pd.DataFrame):
                if not result.stop_loss_effectiveness['summary'].empty:
                    path = self._save_csv(result.stop_loss_effectiveness['summary'], 'entry_stop_loss_effect.csv')
                    exported['entry_stop_loss_effect'] = path

        if hasattr(result, 'hourly_performance') and isinstance(result.hourly_performance, dict):
            if 'summary' in result.hourly_performance and isinstance(result.hourly_performance['summary'], pd.DataFrame):
                if not result.hourly_performance['summary'].empty:
                    path = self._save_csv(result.hourly_performance['summary'], 'entry_hourly_performance.csv')
                    exported['entry_hourly_performance'] = path

        return exported

    def _create_summary_report(
        self,
        daily_events, event_summary,
        time_distribution_result, band_breakout_result,
        price_pattern_result, indicator_validity_result,
        volume_pattern_result, holding_period_result,
        entry_timing_result
    ) -> Path:
        """종합 보고서 Excel 생성"""
        path = self.output_dir / 'summary_report.xlsx'

        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            # 1. 이벤트 목록
            if daily_events is not None and not daily_events.empty:
                daily_events.to_excel(writer, sheet_name='이벤트목록', index=False)

            # 2. 이벤트 요약
            if event_summary is not None and not event_summary.empty:
                event_summary.to_excel(writer, sheet_name='이벤트요약', index=False)

            # 3. 시간대별 분석
            if time_distribution_result and hasattr(time_distribution_result, 'bucket_stats'):
                if isinstance(time_distribution_result.bucket_stats, pd.DataFrame) and not time_distribution_result.bucket_stats.empty:
                    time_distribution_result.bucket_stats.to_excel(writer, sheet_name='시간대별거래대금', index=False)

            # 4. 밴드 돌파 수익률
            if band_breakout_result and hasattr(band_breakout_result, 'post_breakout_returns'):
                if isinstance(band_breakout_result.post_breakout_returns, dict) and 'summary' in band_breakout_result.post_breakout_returns:
                    summary = band_breakout_result.post_breakout_returns['summary']
                    if isinstance(summary, pd.DataFrame) and not summary.empty:
                        summary.to_excel(writer, sheet_name='밴드돌파수익률', index=True)

            # 5. 가격 패턴 MFE/MAE
            if price_pattern_result and hasattr(price_pattern_result, 'mfe_mae'):
                if isinstance(price_pattern_result.mfe_mae, dict) and 'raw_data' in price_pattern_result.mfe_mae:
                    raw = price_pattern_result.mfe_mae['raw_data']
                    if isinstance(raw, pd.DataFrame) and not raw.empty:
                        raw.to_excel(writer, sheet_name='MFE_MAE', index=False)

            # 6. 보유 기간별 수익률
            if holding_period_result and hasattr(holding_period_result, 'period_returns'):
                if isinstance(holding_period_result.period_returns, dict) and 'summary' in holding_period_result.period_returns:
                    summary = holding_period_result.period_returns['summary']
                    if isinstance(summary, pd.DataFrame) and not summary.empty:
                        summary.to_excel(writer, sheet_name='보유기간별수익률', index=False)

            # 7. 진입 타이밍
            if entry_timing_result and hasattr(entry_timing_result, 'optimal_entry_time'):
                if isinstance(entry_timing_result.optimal_entry_time, dict) and 'summary' in entry_timing_result.optimal_entry_time:
                    summary = entry_timing_result.optimal_entry_time['summary']
                    if isinstance(summary, pd.DataFrame) and not summary.empty:
                        summary.to_excel(writer, sheet_name='진입타이밍', index=False)

            # 8. 손절 효과
            if entry_timing_result and hasattr(entry_timing_result, 'stop_loss_effectiveness'):
                if isinstance(entry_timing_result.stop_loss_effectiveness, dict) and 'summary' in entry_timing_result.stop_loss_effectiveness:
                    summary = entry_timing_result.stop_loss_effectiveness['summary']
                    if isinstance(summary, pd.DataFrame) and not summary.empty:
                        summary.to_excel(writer, sheet_name='손절효과', index=False)

            # 9. 거래량 패턴
            if volume_pattern_result and hasattr(volume_pattern_result, 'distribution_pattern'):
                if isinstance(volume_pattern_result.distribution_pattern, dict) and 'details' in volume_pattern_result.distribution_pattern:
                    details = volume_pattern_result.distribution_pattern['details']
                    if isinstance(details, pd.DataFrame) and not details.empty:
                        details.to_excel(writer, sheet_name='거래량패턴', index=False)

        logger.info(f"Created summary report: {path}")
        return path
