"""
PreToolUse Hook: Write / Edit
서비스 .py 파일 수정 시 Step 1 계획 여부 소프트 체크
"""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

data = json.load(sys.stdin)
fp = data.get("file_path", "") or data.get("path", "")

is_service_file = fp.endswith(".py") and "services" in fp and "tests" not in fp

if is_service_file:
    print("\n" + "="*50)
    print("  [WORKFLOW CHECK] 서비스 파일 수정 감지")
    print("="*50)
    print(f"  파일: {fp.split('TheSeven/')[-1]}")
    print()
    print("  체크리스트:")
    print("  □ Step 1 계획서 작성 완료?")
    print("  □ 영향 범위 파악 완료?")
    print("  □ Human Review 완료? (필요한 경우)")
    print("="*50 + "\n")

sys.exit(0)  # 소프트 체크: 항상 통과
