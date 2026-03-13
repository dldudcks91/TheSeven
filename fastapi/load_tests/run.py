"""
부하 테스트 실행 런처

사용법:
  python run.py                        # Phase 목록 표시
  python run.py 1                      # Phase 1 (smoke 프로파일)
  python run.py 1 --profile medium     # Phase 1 (medium 프로파일)
  python run.py 1 --profile heavy --web  # Phase 1 (heavy, 웹 UI 포함)
  python run.py all --profile light    # 전체 Phase 순차 실행

프로파일:
  smoke   — 5명,  30초  (기본 동작 확인)
  light   — 20명, 2분   (경량 부하)
  medium  — 50명, 5분   (Redis 풀 한계 근접)
  heavy   — 100명, 10분 (Redis 풀 초과 예상)
  stress  — 200명, 15분 (서버 한계 탐색)
"""

import argparse
import subprocess
import sys
import os
from config import PROFILES, BASE_URL

PHASE_FILES = {
    "1": ("phase1_api_throughput.py", "API 기본 처리량"),
    "2": ("phase2_march_battle.py", "행군/전투 생성 부하"),
    "3": ("phase3_castle_siege.py", "동시 성 공격"),
    "4": ("phase4_battlefield_ws.py", "전장 + WebSocket"),
    "5": ("phase5_combined.py", "복합 시나리오"),
}


def print_phases():
    print("\n=== TheSeven 부하 테스트 ===\n")
    for key, (filename, desc) in PHASE_FILES.items():
        print(f"  Phase {key}: {desc}  ({filename})")
    print("\n프로파일:")
    for name, cfg in PROFILES.items():
        print(f"  {name:8s} — {cfg['description']}")
    print(f"\n사용법: python run.py <phase|all> [--profile <name>] [--web] [--host <url>]")
    print(f"  기본 호스트: {BASE_URL}")
    print()


def run_phase(phase_key: str, profile: dict, host: str, web: bool = False):
    filename, desc = PHASE_FILES[phase_key]
    print(f"\n{'='*60}")
    print(f"Phase {phase_key}: {desc}")
    print(f"프로파일: {profile['description']}")
    print(f"{'='*60}\n")

    cmd = [
        sys.executable, "-m", "locust",
        "-f", filename,
        "--host", host,
    ]

    if not web:
        cmd.extend([
            "--headless",
            "-u", str(profile["users"]),
            "-r", str(profile["spawn_rate"]),
            "-t", profile["run_time"],
            "--csv", f"results/phase{phase_key}",
            "--html", f"results/phase{phase_key}_report.html",
        ])

    # results 디렉토리 생성
    os.makedirs("results", exist_ok=True)

    print(f"실행: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="TheSeven 부하 테스트 런처")
    parser.add_argument("phase", nargs="?", help="Phase 번호 (1~5) 또는 'all'")
    parser.add_argument("--profile", default="smoke", choices=PROFILES.keys(),
                        help="부하 프로파일 (기본: smoke)")
    parser.add_argument("--host", default=BASE_URL, help=f"서버 URL (기본: {BASE_URL})")
    parser.add_argument("--web", action="store_true", help="Locust 웹 UI 사용")

    args = parser.parse_args()

    if not args.phase:
        print_phases()
        return

    profile = PROFILES[args.profile]

    if args.phase == "all":
        for phase_key in PHASE_FILES:
            rc = run_phase(phase_key, profile, args.host, args.web)
            if rc != 0:
                print(f"\nPhase {phase_key} 실패 (exit code: {rc}). 중단합니다.")
                sys.exit(rc)
        print("\n모든 Phase 완료!")
    elif args.phase in PHASE_FILES:
        rc = run_phase(args.phase, profile, args.host, args.web)
        sys.exit(rc)
    else:
        print(f"알 수 없는 Phase: {args.phase}")
        print_phases()
        sys.exit(1)


if __name__ == "__main__":
    main()
