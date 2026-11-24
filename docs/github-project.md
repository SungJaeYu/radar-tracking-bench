# GitHub 작업 관리

저장소: [SungJaeYu/radar-tracking-bench](https://github.com/SungJaeYu/radar-tracking-bench) · [진행 중 이슈](https://github.com/SungJaeYu/radar-tracking-bench/issues?q=is%3Aissue+is%3Aopen) · [프로젝트 보드](https://github.com/users/SungJaeYu/projects/1).

2026-11-24 기준이다. 구현과 host 검증, 펌웨어 빌드, 실보드 비교 및 릴리스를 구분한다. 일부 항목을 구현했더라도 전체 완료 조건이 남은 이슈는 열어 둔다.

| 이슈 | 완료한 부분 | 남은 범위 |
|---|---|---|
| [#8 PC 시험기](https://github.com/SungJaeYu/radar-tracking-bench/issues/8) | 사전 입력 생성·저장·검증, 선회 전용 FIFO 재생 | 공통 재생 정책, lockstep, 시험 후 일괄 기록, 메모리·오류·timeout 경계 및 부하 검증 |
| [#10 추정기 비교](https://github.com/SungJaeYu/radar-tracking-bench/issues/10) | 선회 잡음 CLI/GUI, KF/EKF 빌드 선택, 소유형 행렬, R 설정, host 회귀·두 firmware 빌드·seed42 초기 실보드 비교 | CT-EKF, 여러 seed·확장 기동·튜닝/평가 조건 분리 및 종합 비교 |
| [#11 공분산 방식 비교](https://github.com/SungJaeYu/radar-tracking-bench/issues/11) | 기준 구현에 Joseph 보정 사용 | Square-root·UD 구현과 수치 안정성·실행 비용 비교 |
| [#4 3D 1/4](https://github.com/SungJaeYu/radar-tracking-bench/issues/4) | 후속 계획 | 좌표계·단위·측정 모델·2D 호환성 |
| [#5 3D 2/4](https://github.com/SungJaeYu/radar-tracking-bench/issues/5) | 후속 계획 | 고도·수직속도·3D 시나리오; #4 이후 |
| [#6 3D 3/4](https://github.com/SungJaeYu/radar-tracking-bench/issues/6) | 후속 계획 | 프로토콜·필터 확장; #4·#5 이후 |
| [#7 3D 4/4](https://github.com/SungJaeYu/radar-tracking-bench/issues/7) | 후속 계획 | GUI·3D 오차·실보드 검증; #5·#6 이후 |

완료된 #1(v1.1.0 릴리스)·#2(GUI 영상·분석)는 이미 closed/completed이며 진행 중 목록에서 제외했다. 근거는 [릴리스 기록](release-v1.1.0.md)과 [영상·분석](analysis/2026-11-23/README.md)에 남긴다.

초기 KF/EKF 실보드4회·3,020개 입력 대응과 결과 그래프는 [실보드 비교](hardware-test-2026-11-24-kf-ekf.md)에 보존한다. #10 전체 완료 조건인 CT-EKF·여러 조건 비교는 남아 있다.

현재 코드와 host/빌드 근거는 [2026-11-24 검증](validation-2026-11-24-estimators.md), 사용법은 [사전 입력](prepared-input.md)·[추정기 설정](estimator-tuning.md)을 따른다. PC 미송신과 RTT는 STM32 불합격이나 기존 v1.1.0 릴리스 차단 조건이 아니다.

과거 CRC 2건은 조치 후 비재현·해결 추정/원인 미확정 이력으로 [릴리스 검증과 실패 분석](release-v1.1.0.md)에 보존한다. 3D·JSBSim·공분산 방식 비교는 기존 릴리스의 필수 조건으로 추가하지 않는다.
