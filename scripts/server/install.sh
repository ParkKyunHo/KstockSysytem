#!/bin/bash
# ============================================================
# K_stock_trading 릴리즈 설치
# ============================================================
# 사용법: ./install.sh <version>
# 예: ./install.sh v2025.12.14.001
#
# 실행 내용:
# 1. 가상환경 생성
# 2. 의존성 설치
# 3. 심볼릭 링크 생성
# ============================================================

set -e

VERSION=$1
BASE_DIR="$HOME/K_stock_trading"
RELEASE_DIR="$BASE_DIR/releases/$VERSION"
SHARED_DIR="$BASE_DIR/shared"

if [ -z "$VERSION" ]; then
    echo "사용법: $0 <version>"
    exit 1
fi

if [ ! -d "$RELEASE_DIR" ]; then
    echo "[오류] 릴리즈 디렉토리 없음: $RELEASE_DIR"
    exit 1
fi

echo "============================================================"
echo " 릴리즈 설치: $VERSION"
echo "============================================================"
echo

# ============================================================
# 1. 가상환경 생성 (Python 3.11 명시)
# ============================================================
echo "[1/3] 가상환경 생성..."
cd "$RELEASE_DIR"

if [ ! -d "venv" ]; then
    python3.11 -m venv venv
    echo "       가상환경 생성됨 (Python 3.11)"
else
    echo "       기존 가상환경 사용"
fi

# ============================================================
# 2. 의존성 설치
# ============================================================
echo
echo "[2/3] 의존성 설치..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
deactivate
echo "       의존성 설치 완료"

# ============================================================
# 3. 심볼릭 링크 생성 (shared 디렉토리)
# ============================================================
echo
echo "[3/3] 심볼릭 링크 생성..."

# logs 링크
if [ ! -L "$RELEASE_DIR/logs" ]; then
    ln -sf "$SHARED_DIR/logs" "$RELEASE_DIR/logs"
fi

# data 링크
if [ ! -L "$RELEASE_DIR/data" ]; then
    ln -sf "$SHARED_DIR/data" "$RELEASE_DIR/data"
fi

# .env 링크
if [ ! -L "$RELEASE_DIR/.env" ]; then
    ln -sf "$SHARED_DIR/.env" "$RELEASE_DIR/.env"
fi

echo "       심볼릭 링크 생성 완료"

echo
echo "============================================================"
echo " 설치 완료: $VERSION"
echo "============================================================"
