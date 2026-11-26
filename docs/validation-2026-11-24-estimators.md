# KF/EKF 선택·PC 시험기 host 및 빌드 검증 — 2026-11-24

대상: [`cd27620`](https://github.com/SungJaeYu/radar-tracking-bench/commit/cd27620d3cd74e22bee963fcf1c4a195fda0e07b), `feat/prepared-input`. v1.1.0 이후 개발 변경이며 새 릴리스 판정은 아니다.

## 반영 범위

- `python -m pc_sim` 통합 진입점과 역할별 simulator/test 폴더 구조.
- GUI 고정 시나리오·선회 잡음 실행, 거리/방위 잡음 입력, 패널 크기 조절·섹션 선택·위치 확대·포트 제안·ANSI 제거.
- 정답·측정·센서 timestamp·완성 프레임의 생성/저장/검증과 선회 전용 FIFO 재생·보고 평가.
- Kconfig KF/EKF 선택과 측정 잡음 R, 공통 estimator API, 소유형 고정 배열 공분산.
- KF 초기 공분산 `static const`, 변수명 정렬, 입력 ASSERT의 하단 private 함수 분리. ASSERT 비활성 빌드에서는 검사 함수와 호출을 제외하며 EKF 수치 실패 방어는 유지한다.

## 결과

| 검증 | 결과 | 범위 |
|---|---:|---|
| 전체 Python | 1,058 passed + 9 subtests | Qt offscreen 포함, UART/시간 모사 및 일부 host C probe |
| Tracking | 27 CTest 통과 | 기본 실행 내부 22함수 + 게이트 20 + KF 설정 4 + EKF 통합 2 |
| handler | 62 CTest 통과 | 같은 31개 회귀를 KF/EKF 각각 실행 |
| EKF 계산 / matrix | 2 / 1 CTest 통과 | 초기화·예측·보정·행렬 연산 |
| UART RX / TX | 45 / 4 CTest 통과 | DRAIN/DISCARD·큐·복구·송신 |
| PERF 구성 | 103 CTest 통과 | monitor 13 + resources 3 + RX 51 + handler 32 + TX 4 |
| ASSERT 비활성 EKF | 별도 2 CTest 통과 | `-D__ASSERT_ON=0`; 테스트 자체의 검증은 활성 |
| STM32 KF / EKF | 두 빌드 통과 | STM32F746G-DISCO, 기존 devicetree unit-address 경고 존재 |

표의 일반 CTest 합계는 **244회**이며 ASSERT 비활성 2회를 추가로 실행했다. `tracking` 내부 22함수를 CTest 개수에 다시 합산하지 않는다. 수집 수만 확인한 결과가 아니라 위 대상 코드에서 실행한 결과다.

| 일반 빌드 | Flash | RAM |
|---|---:|---:|
| KF | 43,348 B | 15,696 B |
| EKF | 50,972 B | 15,696 B |

RAM 값은 링커 영역 사용량이며 함수의 런타임 최대 stack 사용량이 아니다. 같은 ARM 컴파일 옵션의 `-fstack-usage`로 KF adapter `estimator_init`의 정적 stack frame이 184 B에서 24 B로 줄어든 것을 확인했다. 초기 행렬은 읽기 전용 영역에 있고 필터의 공분산에는 복사된다. 두 release ELF에는 입력 ASSERT helper 심볼이 없다.

## 재현 명령

저장소 루트에서 실행한다. Python 3.12, GUI 의존성, CMake/Ninja와 host C compiler가 필요하다. 아래 `build_host_*`는 Git 제외 경로다.

```sh
source ~/zephyrproject/.venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m pytest -q

cmake -G Ninja -S fcc_app/tests/test_tracking -B build_host_tracking -DTRACK_TEST_HOST=ON
cmake --build build_host_tracking
ctest --test-dir build_host_tracking --output-on-failure

cmake -G Ninja -S fcc_app/tests/test_frame_handler -B build_host_handler_kf -DRADAR_TEST_EKF_CV=OFF
cmake --build build_host_handler_kf
ctest --test-dir build_host_handler_kf --output-on-failure
cmake -G Ninja -S fcc_app/tests/test_frame_handler -B build_host_handler_ekf -DRADAR_TEST_EKF_CV=ON
cmake --build build_host_handler_ekf
ctest --test-dir build_host_handler_ekf --output-on-failure

for suite in test_matrix test_ekf_cv test_uart_rx test_uart_tx test_perf_monitor test_perf_resources; do
    cmake -G Ninja -S fcc_app/tests/$suite -B build_host_$suite
    cmake --build build_host_$suite
    ctest --test-dir build_host_$suite --output-on-failure
done

for suite in test_frame_handler test_uart_rx test_uart_tx; do
    cmake -G Ninja -S fcc_app/tests/$suite -B build_host_${suite}_perf -DPERF_TEST_ENABLED=ON
    cmake --build build_host_${suite}_perf
    ctest --test-dir build_host_${suite}_perf --output-on-failure
done

cmake -G Ninja -S fcc_app/tests/test_ekf_cv -B build_host_ekf_noassert -DCMAKE_C_FLAGS=-D__ASSERT_ON=0
cmake --build build_host_ekf_noassert
ctest --test-dir build_host_ekf_noassert --output-on-failure
```

Zephyr workspace에서 `<repo>`를 실제 절대 경로로 바꿔 실행한다.

```sh
west build -d <repo>/build -b stm32f746g_disco <repo>/fcc_app -- -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
west build -d <repo>/build_ekf -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=ekf.conf -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

## 검증 경계와 남은 작업

이 host·빌드 검증 이후 별도로 [KF/EKF 실보드4회 비교](hardware-test-2026-11-24-kf-ekf.md)를 수행했다. 두 기록의 대상과 범위를 구분한다.

이 문서의 검증에는 flash나 새로운 실보드 HIL 실행이 포함되지 않는다. 모사 UART·host 수치 검증과 firmware 빌드를 실제 센서 정확도, 보드 실행 시간, 최대 stack 여유의 증거로 사용하지 않는다. 기존 보드 결과는 [v1.1.0 기록](release-v1.1.0.md)의 대상 코드에 한정된다.

#8의 모든 입력용 공통 재생·lockstep·시험 후 일괄 기록, #10의 다중 seed KF/EKF·CT-EKF 비교와 확장 기동, #11의 Square-root·UD 비교는 별도 완료 조건이다. [진행 중 작업](github-project.md).
