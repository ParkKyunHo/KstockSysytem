#!/bin/bash
# ============================================================
# K_stock_trading 롤백
# ============================================================
# 사용법:
#   ./rollback.sh previous         - 이전 버전으로 롤백
#   ./rollback.sh v2025.12.14.001  - 특정 버전으로 롤백
# ============================================================

set -e

TARGET=$1
BASE_DIR="$HOME/K_stock_trading"
RELEASES_DIR="$BASE_DIR/releases"
CURRENT_LINK="$BASE_DIR/current"

echo "============================================================"
echo " K_stock_trading 롤백"
echo "============================================================"
echo

# 현재 버전 확인
CURRENT_VERSION=$(cat "$CURRENT_LINK/VERSION" 2>/dev/null || echo "none")
echo " 현재 버전: $CURRENT_VERSION"

# 가용 버전 목록
echo
echo " 가용 버전:"
ls -1 "$RELEASES_DIR" | sort -r

# 타겟 버전 결정
if [ "$TARGET" = "previous" ] || [ -z "$TARGET" ]; then
    # 현재 버전 바로 이전 버전 찾기
    VERSIONS=($(ls -1 "$RELEASES_DIR" | sort -r))

    for i in "${!VERSIONS[@]}"; do
        if [ "${VERSIONS[$i]}" = "$CURRENT_VERSION" ]; then
            if [ $((i+1)) -lt ${#VERSIONS[@]} ]; then
                TARGET_VERSION="${VERSIONS[$((i+1))]}"
                break
            fi
        fi
    done

    if [ -z "$TARGET_VERSION" ]; then
        echo
        echo "[오류] 이전 버전을 찾을 수 없습니다."
        exit 1
    fi
else
    TARGET_VERSION="$TARGET"
fi

echo
echo " 롤백 대상: $TARGET_VERSION"

# 타겟 버전 존재 확인
if [ ! -d "$RELEASES_DIR/$TARGET_VERSION" ]; then
    echo
    echo "[오류] 버전 없음: $TARGET_VERSION"
    exit 1
fi

# 롤백 실행
echo
echo " 롤백 실행 중..."

# 1. 서비스 중지
sudo systemctl stop k-stock-trading 2>/dev/null || true

# 2. 심볼릭 링크 전환
rm -f "$CURRENT_LINK"
ln -s "$RELEASES_DIR/$TARGET_VERSION" "$CURRENT_LINK"

# 3. 서비스 시작
sudo systemctl start k-stock-trading

# 새 버전 확인
NEW_VERSION=$(cat "$CURRENT_LINK/VERSION" 2>/dev/null || echo "unknown")

echo
echo "============================================================"
echo " 롤백 완료!"
echo "============================================================"
echo
echo " 이전: $CURRENT_VERSION"
echo " 현재: $NEW_VERSION"
echo
