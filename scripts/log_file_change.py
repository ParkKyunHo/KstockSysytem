#!/usr/bin/env python3
"""
Claude Code Hook: 파일 변경 자동 로깅
PostToolUse (Edit/Write) 이벤트 발생 시 CLAUDE.md에 기록
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# 로깅 제외 대상 패턴
IGNORED_PATTERNS = [
    '__pycache__',
    '.git',
    '.pytest_cache',
    '.pyc',
    '.env',
    'node_modules',
    '.claude',        # Hook 설정 파일 자체 제외
    'CLAUDE.md',      # 무한 루프 방지
]


def get_hook_input():
    """stdin에서 Hook 입력 파싱"""
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def should_log(file_path: str) -> bool:
    """로깅 대상 여부 판단"""
    return not any(pattern in file_path for pattern in IGNORED_PATTERNS)


def append_to_work_log(file_path: str, tool_name: str):
    """CLAUDE.md Work Log 섹션에 항목 추가"""
    claude_md = Path("C:\\K_stock_trading\\CLAUDE.md")

    if not claude_md.exists():
        return

    # 상대 경로 계산
    try:
        rel_path = Path(file_path).relative_to("C:\\K_stock_trading")
    except ValueError:
        rel_path = Path(file_path).name

    # 현재 날짜
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H:%M")
    action = "Modified" if tool_name == "Edit" else "Created"
    entry = f"- [{timestamp}] {action}: `{rel_path}`"

    # 파일 읽기
    content = claude_md.read_text(encoding='utf-8')
    lines = content.split('\n')

    # Work Log 섹션 찾기
    work_log_idx = None
    for i, line in enumerate(lines):
        if '## 작업 기록 (Work Log)' in line:
            work_log_idx = i
            break

    if work_log_idx is None:
        return

    # 오늘 날짜 섹션 찾기 또는 생성
    today_header = f"### {today}"
    today_section_idx = None

    for i in range(work_log_idx + 1, len(lines)):
        if lines[i].strip() == today_header:
            today_section_idx = i
            break
        if lines[i].startswith('### ') or lines[i].startswith('---'):
            # 오늘 날짜 섹션이 없음 - 새로 생성
            lines.insert(i, "")
            lines.insert(i, today_header)
            today_section_idx = i
            break

    if today_section_idx is None:
        return

    # 엔트리 삽입 위치 찾기 (오늘 섹션 바로 다음)
    insert_idx = today_section_idx + 1
    lines.insert(insert_idx, entry)

    # 파일 쓰기
    claude_md.write_text('\n'.join(lines), encoding='utf-8')


def main():
    hook_input = get_hook_input()

    tool_input = hook_input.get('tool_input', {})
    file_path = tool_input.get('file_path', '')
    tool_name = hook_input.get('tool', 'Unknown')

    if file_path and should_log(file_path):
        append_to_work_log(file_path, tool_name)


if __name__ == '__main__':
    main()
