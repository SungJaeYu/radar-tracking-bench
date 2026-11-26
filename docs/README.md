# 문서 안내

최신 개발 상태: [확장 기동 STM32 분석](analysis/maneuver-grid-20261126/README.md), [CT-EKF 고정 선회 비교](test-results/ct-ekf-2026-11-24/README.md), [확장 기동 정답 모델](test-results/maneuver-models-2026-11-25/README.md), [v1.2.0 릴리스 범위·검증·보드 증거 출처](release-v1.2.0.md). 이전 KF/EKF 비교는 [Q 설정·host 탐색](test-results/ekf-q-2026-11-24/README.md)과 [독립 시드·이탈 선회·실보드 비교](test-results/ekf-q-board-2026-11-24/README.md)에 있다. STM32 판정은 해당 시험의 관측 부하·펌웨어 근거 범위에서 읽고 PC 미송신·RTT와 분리한다.

[송신 시한 경과 sleep 수정·최종60초 검증](test-results/host-pacing-fix-2026-11-23/README.md)과 [30분 실보드 기록](test-results/host-input-retest-2026-11-23/README.md)을 함께 제공한다. 과거 결과는 당시 판정 그대로 보존한다.

[GUI 무음 영상·분석](analysis/2026-11-23/README.md)은 저장된 실보드 세션의 재생, 그래프와 수치 표를 포함한다. [GitHub 작업 목록](github-project.md)에서 PC 시험기 개선, v1.2.0 추정기 비교, 3D 확장을 추적한다.

[English overview](../README.md) · [Architecture in English](../EXPLAINER.en.md)

[한국어 프로젝트 소개](../README.ko.md)에서 전체 구성을 확인한 뒤, 목적에 맞는 문서를 선택하세요.

## 처음 보는 분께

1. [구현 흐름](../EXPLAINER.md) — PC 입력부터 ISR·링버퍼·스레드·추정 결과 반환까지
2. [V1 완료 범위](roadmap.md) — 구현한 범위, 검증 근거, 후속 확장
3. [시스템 역할](system-roles.md) — PC·펌웨어의 책임과 측정/트랙 ID 정책

## 실행과 사용

| 목적 | 안내 |
|---|---|
| 보드 연결·펌웨어 빌드·기본 통신 | [보드 시작 안내](board-bringup.md) |
| GUI 연결·미리보기·그래프·상태 조회 | [GUI 사용법](../pc_sim/GUI.md) |
| 측정 송신·CSV·잡음/이상치 평가 | [PC CLI](../pc_sim/README.md) |
| 동일 시험 입력의 생성·저장·변경 검증·선회 재생 | [사전 생성 입력](prepared-input.md) |
| KF/EKF 선택·R/EKF Q 설정·행렬 소유권 | [추정기 구성](estimator-tuning.md) |
| 로그 레벨·디버그 빌드 | [펌웨어 로그 설정](board-bringup.md#펌웨어-로그-설정) |

## 설계와 테스트

| 목적 | 문서 |
|---|---|
| UART 규격·요구사항·구현·테스트 연결 | [요구사항 추적표](requirements-traceability.md) |
| 현재 개발 브랜치의 host·펌웨어 검증 | [2026-11-24 검증](validation-2026-11-24-estimators.md) |
| EKF Q 12값의 같은 입력 host 비교 | [표·그래프·재현](test-results/ekf-q-2026-11-24/README.md) |
| 고정 Q 후보·독립 시드·이탈 선회 host336회/보드46회 | [원시 자료·그래프6종·재분석](test-results/ekf-q-board-2026-11-24/README.md) |
| 자동 테스트 실행과 검증 범위 | [영역별 실행](../tests/README.md) · [테스트 목록](test-cases.md) |
| ISR·인터럽트 차단 구간 점검 | [계측 실행 문맥](performance-monitoring.md#인터럽트와-계측-실행-문맥) |
| STM32 판정 기준과 미검증 영역 | [성능 검증 범위](stm32-performance-coverage.md) |
| RTT·보드 지연·큐·스택의 측정 방법 | [성능 계측](performance-monitoring.md) |
| C/Python 작성 규칙·API 계약 | [펌웨어 코딩 스탠다드](coding-standard.md) · [Python 코딩 스탠다드](python-coding-standard.md) |

## 실보드 검증 결과

v1.2.0 비교와 이 후보에서 실행한 host 검증은 [v1.2.0 릴리스 기록](release-v1.2.0.md)을 확인하세요. v1.1.0의 별도 보드 부하·실패 이력은 [v1.1.0 검증과 실패 분석](release-v1.1.0.md)에 보존합니다.

| 확인할 내용 | 기록 |
|---|---|
| 세 추정기의 확장 기동·잡음 동일 입력 STM32 비교 | [80조건 분석·재현·펌웨어 출처](analysis/maneuver-grid-20261126/README.md) |
| KF/EKF 동일 입력 초기 비교·오차·실행 시간 | [2026-11-24 실보드 결과·그래프](hardware-test-2026-11-24-kf-ekf.md) |
| v1.1.0 선회·영어 GUI·전체 자동 회귀 | [v1.1.0 검증](hardware-test-2026-11-23-v1.1.0.md) |
| 전체 검증 현황과 날짜별 이력 | [검증 기록](verification-history.md) |
| 정상·잡음·누락 추적 평가, GUI·CSV | [고정 시나리오 평가](hardware-test-2026-11-18-evaluation.md) |
| 잡음100회·이상치49회, 짧은 RTT 회귀 | [확장 추적 평가](hardware-test-2026-11-19-noise-spike.md) |
| 30분 송수신·지연·스택 관측 | [성능 시험](hardware-test-2026-11-19-performance.md) |
| 링 overflow·RX/TX 포화·오래된 측정 복귀 | [전송 오류 시험](hardware-test-2026-11-18-transport-stress.md) |
| INIT/RESET 유실·FIFO 순서·TRACK TX 포화 | [제어·TRACK 시험](hardware-test-2026-11-18-track-controls.md) |
| 데이터 선 단절·재연결 | [물리 통신 장애 시험](hardware-test-2026-11-14-link-loss.md) |

수치는 각 기록의 대상 버전·설정·입력 조건에 한해 해석합니다. host 테스트와 실보드 시험을 구분하며, 과거 실패 판정은 이후 기준 변경으로 덮어쓰지 않습니다. 원시 CSV·콘솔·해시와 재평가 명령은 해당 시험 문서에서 연결합니다.

현재 후속 작업 후보는 [로드맵](roadmap.md#다음-구현-순서)에서 관리합니다.

- [2026-11-22 로그 형식 통일·GUI/PC·실보드 회귀](hardware-test-2026-11-22-logging.md)
