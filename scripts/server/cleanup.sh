#!/bin/bash
# ============================================================
# K_stock_trading 정리
# ============================================================
# 사용법: ./cleanup.sh
#
# 실행 내용:
# 1. 오래된 릴리즈 삭제 (최근 5개 유지)
# 2. 오래된 로그 정리
# ============================================================

BASE_DIR="$HOME/K_stock_trading"
RELEASES_DIR="$BASE_DIR/releases"
LOGS_DIR="$BASE_DIR/shared/logs"
CURRENT_LINK="$BASE_DIR/current"

MAX_RELEASES=5
MAX_LOG_DAYS=7

echo "============================================================"
echo " K_stock_trading 정리"
echo "============================================================"
echo

# 현재 버전 확인 (삭제 방지)
CURRENT_VERSION=$(basename "$(readlink -f "$CURRENT_LINK")" 2>/dev/null || echo "")

# ============================================================
# 1. 오래된 릴리즈 삭제
# ============================================================
echo "[1/2] 오래된 릴리즈 정리..."

RELEASE_COUNT=$(ls -1 "$RELEASES_DIR" 2>/dev/null | wc -l)
echo "       현재 릴리즈 수: $RELEASE_COUNT"
echo "       유지 개수: $MAX_RELEASES"

if [ "$RELEASE_COUNT" -gt "$MAX_RELEASES" ]; then
    # 오래된 순으로 정렬하여 삭제 대상 선정
    DELETE_COUNT=$((RELEASE_COUNT - MAX_RELEASES))

    for VERSION in $(ls -1 "$RELEASES_DIR" | sort | head -n "$DELETE_COUNT"); do
        # 현재 버전은 삭제하지 않음
        if [ "$VERSION" = "$CURRENT_VERSION" ]; then
            echo "       ⏭️  $VERSION (현재 버전, 스킵)"
            continue
        fi

        echo "       🗑️  $VERSION 삭제 중..."
        rm -rf "$RELEASES_DIR/$VERSION"
    done

    echo "       삭제 완료"
else
    echo "       정리 불필요"
fi

# ============================================================
# 2. 오래된 로그 정리
# ============================================================
echo
echo "[2/2] 오래된 로그 정리..."

if [ -d "$LOGS_DIR" ]; then
    OLD_LOGS=$(find "$LOGS_DIR" -name "*.log.*" -mtime +$MAX_LOG_DAYS 2>/dev/null | wc -l)

    if [ "$OLD_LOGS" -gt 0 ]; then
        echo "       $OLD_LOGS개 오래된 로그 파일 삭제..."
        find "$LOGS_DIR" -name "*.log.*" -mtime +$MAX_LOG_DAYS -delete 2>/dev/null
        echo "       삭제 완료"
    else
        echo "       정리할 로그 없음"
    fi
else
    echo "       로그 디렉토리 없음"
fi

# ============================================================
# 결과
# ============================================================
echo
echo "============================================================"
echo " 정리 완료"
echo "============================================================"
echo
echo " 현재 릴리즈:"
ls -1 "$RELEASES_DIR" 2>/dev/null | sort -r
echo
