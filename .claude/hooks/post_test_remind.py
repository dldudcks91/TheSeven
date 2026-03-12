"""
PostToolUse Hook: Write / Edit
테스트 파일 수정 후 pytest 실행 리마인더
"""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

data = json.load(sys.stdin)
fp = data.get("file_path", "") or data.get("path", "")

is_test_file = "tests" in fp and fp.endswith(".py")

if is_test_file:
    print("\n" + "="*50)
    print("  [TEST REMINDER] 테스트 파일 수정됨")
    print("="*50)
    print("  pytest 실행 필요:")
    print("  cd fastapi && python -m pytest tests/ -v")
    print()
    print("  기존 테스트 회귀 확인도 함께 진행하세요.")
    print("="*50 + "\n")

sys.exit(0)
