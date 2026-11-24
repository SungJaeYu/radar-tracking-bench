# KF/EKF 실보드 비교 데이터

[결과와 그래프](../../hardware-test-2026-11-24-kf-ekf.md) · [집계 CSV](summary.csv) · [집계 JSON](summary.json) · [표본별 데이터](series.csv).

실행 소스: `4a9e6eaad3c3063d99e7821913396e9b53a6da78`. 두 PERF 구성과 일반 KF 복원 이미지의 해시·최종 STATUS를 원시 manifest에 기록했다. `evidence.tar.gz`는 입력·송수신 wire/CSV·console·flash/build 로그·전체 설정·실행 스크립트를 담는다. firmware HEX/ELF 자체는 포함하지 않으며 원래 로컬 기록에 보존한다. 모든 측정은 합성 입력이고 추정 결과는 실제 STM32 출력이다.

## 동일 입력 해시

| 조건 | samples.jsonl SHA256 |
|---|---|
| baseline | `066508f099dd101d1bb7981286274c2a315c9c2273e0c18874c09a429ff00eda` |
| noisy | `312087235885450cbbcca569547d3501a55b91c9c6d11ac47abd83fd1dab2154` |

## Flash 이미지 해시

| 구성 | zephyr.hex SHA256 |
|---|---|
| kf | `85e558d08862a9ecc0c1d9fc886974f981bd31c8371bd15cf338b564035cf702` |
| ekf | `221fe3909a850c823b40d5ede52afb293e27add1dedb1d8bc811ae78136851e4` |
| restore | `f0572f1b699d0ffb044b25a332eace3f15013c52efedd2fa2ffa55b86cf03b26` |

## 오프라인 재현

저장소 루트에서 GUI 의존성과 NumPy가 설치된 Python 환경을 사용한다. 이 명령은 보드에 접근하지 않는다. 결과를 새 디렉터리에 재생성해 공개 자료와 대조할 수 있다.

```sh
mkdir -p /tmp/radar-kf-ekf-evidence
tar -xzf docs/test-results/kf-ekf-2026-11-24/evidence.tar.gz -C /tmp/radar-kf-ekf-evidence
python docs/test-results/kf-ekf-2026-11-24/analyze.py /tmp/radar-kf-ekf-evidence/recording --output /tmp/radar-kf-ekf-analysis
python docs/test-results/kf-ekf-2026-11-24/reference_ekf.py /tmp/radar-kf-ekf-evidence/recording --output /tmp/radar-kf-ekf-analysis
QT_QPA_PLATFORM=offscreen python docs/test-results/kf-ekf-2026-11-24/plot.py /tmp/radar-kf-ekf-analysis
```

`analyze.py`는 raw wire→보고 CSV, 입력→TX, 보존 입력, timestamp 대응, PERF 오류, 상태 및 구간별 통계를 검사한다. `reference_ekf.py`는 gate 거부·재시작이 없는 이번 두 EKF 실행에 한해 NumPy float64 계산과 보드 출력을 대조한다. 모든 tracker 정책이나 내부 float 공분산의 PSD를 검증하는 일반 테스트는 아니다.

실보드 재현은 먼저 같은 코드·설정으로 `build_compare_kf`(perf.conf), `build_compare_ekf`(perf.conf;ekf.conf), 일반 `build`를 빌드한 후 archive의 `recording/run_comparison.py --help`를 참고한다. 이 실행기는 연결된 STM32를 flash하고 UART를 독점 사용하며 종료 시 일반 KF로 복원한다. 출력 디렉터리는 새 경로여야 한다.

무잡음/잡음 모두755개 입력, 첫2초 제외735개 공통 평가 시각이다. 세션별·표본별 원본은 archive에 있고 CSV/그래프는 그 파생 자료다. 파일 무결성은 [SHA256SUMS](SHA256SUMS)로 확인한다. 해시는 우발적 변경 감지용이며 서명이나 인증은 아니다.
