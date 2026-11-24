# CT-EKF 수치 검증 및 동일 입력 비교 — 2026-11-24

**완료: 호스트 252회, STM32 18회 동일 입력 비교.** 보드에 보낸 측정 **13,590개 모두** 대응했고, 게이트 거부·LOST·STATUS 오류는 0이었다. 일반 KF 펌웨어를 복구하고 STATUS 8개 항목이 모두 0임을 확인했다. 기록 이름은 2026-11-24 실험을 유지하며 최종 정리는 11월25일에 완료했다.

CT는 독립 시드의 다수 조건에서 CV 후보보다 위치 RMSE가 작았지만, 멀어지는 경로의 강한 잡음 seed6에서는 조금 더 컸다. CT의 계산 비용도 증가했다. 아래 정확도·비용·불리한 결과를 함께 비교한다.

## 구현과 좌표계

새 `EKF_CT` 선택지는 기존 공통 estimator 인터페이스를 사용한다. 기본 polar KF 선택과 기존 CV-EKF 계산은 유지한다. GUI에서 실행 중 필터를 바꾸지 않으며, `fcc_app/ekf_ct.conf`로 빌드 시 선택한다.

상태 순서는 `[x, y, vx, vy, omega]`다. x는 동쪽, y는 북쪽이며 위치 m, 속도 m/s, 선회율 rad/s를 사용한다. 양의 omega는 시계방향이다. 레이더 방위각은 `atan2(x, y)`로 계산한다.

`a = omega * dt`, `A = sin(a) / omega`, `B = (1-cos(a)) / omega`일 때:

```text
x'     = x + A*vx + B*vy
y'     = y - B*vx + A*vy
vx'    = cos(a)*vx + sin(a)*vy
vy'    = -sin(a)*vx + cos(a)*vy
omega' = omega
```

omega가 0에 가까우면 sinc 계열의 급수로 계산하여 0 나눗셈과 작은 값의 뺄셈 오차를 피한다. 공분산 예측에는 해석적 Jacobian을 사용한다. 거리·방위각 관측의 각도 잔차를 정규화하고, 보정에는 스케일링한 2×2 Cholesky 풀이와 Joseph 공분산식을 사용한다. 원점에 너무 가깝거나 수치 계산이 실패하면 상태와 공분산을 함께 유지한다. 대칭 PSD 공분산은 호출 계약이며, 런타임의 유한값·대각 검사만으로 PSD를 증명하지는 않는다.

공분산은 구조체가 고정 배열로 소유한다. CT 빌드 전체에 최대 행·열 5를 적용하고, 기존 KF/CV 빌드의 기본 최대 크기 4는 유지한다. 동적 할당이나 호출자 버퍼를 보관하지 않는다.

## 과정 잡음과 초기화

이번 모델은 다음 이산 가산 잡음을 사용한다.

```text
G = [[dt²/2, 0,     0 ],
     [0,     dt²/2, 0 ],
     [dt,    0,     0 ],
     [0,     dt,    0 ],
     [0,     0,     dt]]
Q = G * diag(q_acc, q_acc, q_alpha) * Gᵀ
```

- `q_acc`: Cartesian 가속도 분산, m²/s⁴.
- `q_alpha`: 각가속도 분산, rad²/s⁴.
- `P_omega`: 초기 선회율 분산, rad²/s².

이산 잡음 배치의 참고는 [MathWorks motion-model state and process noise](https://www.mathworks.com/help/fusion/ug/motion-model-state-and-process-noise.html)다. 이 구현은 상태 순서와 각도 단위·시계방향 부호를 위 계약에 맞췄으며, 참고 자료의 각도 관례를 그대로 사용하지 않는다.

각가속도 잡음은 다음 상태의 omega에 더해진다. 같은 시간 간격의 선회 궤적 안에서 각가속도를 적분한 모델은 아니다. `q_acc`, `q_alpha`는 표준편차가 아닌 분산이다.

초기 위치 공분산 및 속도 공분산의 4×4 부분은 기존 CV-EKF의 polar-to-Cartesian 변환과 같다. 초기 속도와 omega는 0이며, 참값 속도나 참값 선회율을 주입하지 않는다. 초기 omega 분산은 0.01 rad²/s²다. 측정 R, 공통 게이트, 추적 상태 전이는 기존 설정을 사용한다.

## 후보 선택과 독립 시드

기존 Q 실험의 저장 입력 84개를 복사해 사용한다. 두 경로 각각 무잡음 seed 42, nominal seed 42, 독립 seed 1–10 × 잡음 4조건으로 구성된다. 각 입력은 세 필터에 동일하게 들어간다. 호스트 실행은 총 252회다.

CT 후보는 **original 경로의 seed 42 두 입력만** 사용해 선택했다.

- `q_acc ∈ {10, 100, 1000}` m²/s⁴.
- `q_alpha ∈ {0.000001, 0.0001, 0.01}` rad²/s⁴.
- 두 입력에서 coverage 100%, LOST 0인 후보 중 nominal seed 42의 첫 2초 이후 위치 RMSE가 가장 작은 후보를 선택.
- 선택 결과: `q_acc=100`, `q_alpha=0.01`, `P_omega=0.01`. nominal seed 42 RMSE는 **14.859 m**.

이 값을 고정한 뒤 전체 입력을 평가했다. 실험 설정은 [configs/ct.conf](configs/ct.conf)에 보관한다. CT Kconfig의 잠정 기본 `q_alpha=0.0001`과 실험 선택값은 구분하며, 이 결과로 기본 설정을 자동 변경하지 않는다. CV 비교 후보는 앞선 실험의 `q_acc=10000`이다.

## 호스트 결과

252회 모두 coverage 100%, 게이트 거부 0, LOST 0이었다. 기존 KF/CV의 168회 결과는 이전에 보관한 라이브러리로 재생한 출력과 바이트 단위로 같았다.

아래 값은 독립 seed 1–10 각각의 공통 유효 시각 위치 RMSE를 계산한 뒤 그 10개를 평균한 값이다. 초기 2초를 제외한다. 단위는 m다.

| 경로 | 주입 잡음 표준편차 | Polar KF | CV-EKF q=10000 | CT-EKF |
|---|---|---:|---:|---:|
| Original | 거리 10 m / 방위 0.01 rad | 30.129 | 22.005 | 14.541 |
| Original | 거리 20 m / 방위 0.02 rad | 59.711 | 44.943 | 34.360 |
| 처음부터 멀어지는 경로 | 거리 10 m / 방위 0.01 rad | 34.114 | 24.769 | 17.772 |
| 처음부터 멀어지는 경로 | 거리 20 m / 방위 0.02 rad | 68.188 | 50.661 | 47.365 |

CT의 RMSE가 CV 후보보다 작은 독립 입력은 80개 중 74개였다. 모든 조건에서 우월하지는 않다. 예를 들어 멀어지는 경로의 strong seed 6은 CV **47.149 m**, CT **48.029 m**로 CT가 조금 더 컸다. 불리한 결과도 전체 표와 그래프에 포함한다.

두 경로 모두 일부 구간에서 거리가 증가한다. `outbound`는 처음부터 반경 바깥 방향으로 출발하는 경로를 뜻하며, 기존 경로와 비교해 거리·방위 기하가 달라진다. 동일 잡음 표본을 유지하지만 Cartesian 위치 오차는 거리와 함께 달라질 수 있다.

## 수치 검증

[numeric_reference.py](numeric_reference.py)는 production CT C 코드를 읽어 독립 NumPy float64 계산과 비교한다. 예측 공분산의 기준 Jacobian은 중앙차분으로 계산한다. ASSERT 비활성·활성 각각 51개 예측 조건, 3개 보정 조건, 10,000회 반복 갱신을 검증한다. 0·근접 0·양/음 선회율, 방위각 경계, 공분산 고유값을 포함한다. CTest 22개(11사례 × ASSERT 0/2)는 초기 공분산 소유, 좌/우 90도 선회, Q, dt=0, 각도 경계, 수치 실패 보존, 잘못된 공분산 차원·비유한 공분산·보정 overflow, lifecycle, 설정 연결을 검증한다. 51개 예측 조건에는 급수 전환 임계값 양쪽의 6개 조건을 포함한다. [수치 검증 결과](numeric-results.json).

독립 수치 기준은 필터 수학 검증이고, 호스트 저장 입력 비교는 공통 처리기·게이팅·상태 전이를 포함한다. 어느 쪽도 실보드 실행시간이나 실제 레이더 잡음 분포를 측정하지 않는다.

## 실보드 결과

사전에 고정한 18회를 모두 수행했다.

```text
2 경로 × {baseline42, nominal6, strong6} × {KF, CV-EKF, CT-EKF}
```

보드는 STM32F746G-DISCO, 데이터와 콘솔은 각각 115200 baud다. 매 실행마다 해당 PERF 펌웨어를 플래시하고 재부팅했다. 각 실행의 입력 755개·TRACK 보고 757개(측정 대응 755개와 reset 보고 2개)·STATUS 보고 2개를 원시 UART에서 다시 해독했다. 입력 바이트와 시각, 저장 CSV, 원시 콘솔의 PERF 집계가 일치했다. 18회 모두 coverage 100%, 게이트 거부·LOST·STATUS 오류 0이었다. 관측된 RX 완료→TX 제출 최대값은 KF 1 ms, CV 2 ms, CT 3 ms이며 20 ms 초과는 없었다.

다음 표는 공통 유효 시각의 위치 RMSE(m)다. 초기 2초를 제외했으며 전체 초기화 기록은 원시 자료에 남아 있다.

| 경로 | 입력 | Polar KF | CV-EKF q=10000 | CT-EKF |
|---|---|---:|---:|---:|
| Original | 무잡음 seed42 | 4.513 | 9.603 | 0.598 |
| Original | nominal seed6 | 30.277 | 22.253 | 13.540 |
| Original | strong seed6 | 60.025 | 41.906 | 31.628 |
| 처음부터 멀어지는 경로 | 무잡음 seed42 | 0.974 | 11.714 | 1.773 |
| 처음부터 멀어지는 경로 | nominal seed6 | 34.289 | 25.396 | 16.804 |
| 처음부터 멀어지는 경로 | strong seed6 | 68.461 | 47.149 | 48.030 |

CT가 CV 후보보다 나은 것은 6조건 중 5조건이다. 멀어지는 경로의 strong seed6에서는 CV보다 RMSE가 컸고, 같은 경로의 무잡음에서는 polar KF가 CT보다 작았다. 기본값 변경이나 모든 기동에서의 우월성을 주장하지 않는다. 전체·선회 전·선회·선회 후 지표는 [summary.csv](summary.csv), 같은 시각의 비교는 [paired.csv](paired.csv)에 있다.

호스트와 보드의 state/result/valid/eligible은 모든 측정에서 같았다. 유효 위치의 최대 차이는 KF 0 m, CV 약 0.01141 m, CT 약 **0.019454 m**였다. 서로 다른 컴파일러·수학 라이브러리 환경의 float 결과를 바이트 동일하다고 주장하지 않는다.

## 실행 비용과 메모리

아래 평균은 각 필터의 6회 실행에서 관측한 호출 평균의 평균이고, 최대는 6회 전체의 가장 큰 단일 호출이다. 동일 PERF 계측을 사용했다. 단위는 μs다.

| 필터 | predict 평균 / 최대 | correct 평균 / 최대 | handler 최소 미사용 스택 |
|---|---:|---:|---:|
| Polar KF | 28.267 / 29.263 | 33.743 / 35.388 | 1,104 B |
| CV-EKF q=10000 | 176.811 / 1,249.236 | 521.057 / 530.379 | 736 B |
| CT-EKF | 523.110 / 530.680 | 697.810 / 1,893.953 | 784 B |

CV predict의 **1,249.236 μs**, CT correct의 **1,893.953 μs** 최대값도 그대로 보존했다. 계측 구간에는 스케줄링·인터럽트의 영향이 포함될 수 있으며 해당 큰 값의 원인을 이 실험만으로 확정하지 않는다. 순수 명령 실행시간이나 WCET로 해석하지 않는다. handler 할당은 기존 2,048 B를 유지했으며 CT 때문에 늘리지 않았다. 이 여유는 이번 경로·잡음·관측 부하에서 얻은 값이다.

빌드 로그의 전체 FLASH/RAM 사용량은 다음과 같다. 일반 빌드는 Kconfig 기본값, PERF 비교 빌드는 위 고정 후보를 사용했다.

| 필터 | 일반 FLASH | 일반 RAM | PERF FLASH | PERF RAM |
|---|---:|---:|---:|---:|
| Polar KF | 43,348 B | 15,696 B | 48,708 B | 21,184 B |
| CV-EKF | 50,972 B | 15,696 B | 56,332 B | 21,184 B |
| CT-EKF | 52,236 B | 15,696 B | 57,604 B | 21,184 B |

ARM 빌드에서 확인한 구조체 크기는 다음과 같다. 전체 RAM과 개별 상태 크기는 다른 지표다.

| 필터 target | `sizeof(matrix)` | `sizeof(estimator)` | `sizeof(track)` |
|---|---:|---:|---:|
| Polar KF | 72 B | 176 B | 192 B |
| CV-EKF | 72 B | 88 B | 104 B |
| CT-EKF | 108 B | 128 B | 144 B |

기존 KF는 거리·방위에 각각 필터를 가지므로 CT보다 전체 estimator 구조체가 클 수 있다. CT는 5×5 고정 저장소를 사용하되 가변 크기 할당이나 외부 배열 참조를 추가하지 않았다. 빌드 로그, ARM stack-usage 파일과 `state-sizes.json`은 원시 아카이브에 포함한다.

## 그래프

| 그림 | 내용 |
|---|---|
| [경로와 레이더 거리](geometry-and-range.png) | 동일 잡음의 두 경로와 추정 위치, 거리 변화 |
| [멀어지는 선회 오차](outbound-board-errors.png) | nominal/strong seed6, 동일 y축 범위 |
| [nominal 잡음 오차](nominal-board-errors.png) | 두 경로의 시각별 보드 위치 오차 |
| [strong 잡음 오차](strong-board-errors.png) | 불리한 CT 결과까지 포함한 비교 |
| [독립 시드 결과](host-independent-seeds.png) | seed1–10별 RMSE의 평균과 관측 최소/최대 |
| [보드 실행시간](board-execution.png) | predict/correct 평균·관측 최대와 스택 여유 |

시드 최소/최대는 신뢰구간이 아니며, seed42 선택 결과는 독립 시드 집계에서 제외했다. 선회 영역과 초기 2초 제외 구간은 그래프 주석을 따른다.

## 근거와 재현

`source_commit`의 `6b9e529e96abaa8b492963cf764246b72e58f77e`는 **CT 변경 전 기준 커밋**이다. 실험은 이 기준에 CT 구현을 추가한 작업 트리에서 실행했다. 이 값만으로 CT 소스를 재현할 수 없다. 정확한 실행 소스는 [source-manifest.json](source-manifest.json)의 SHA-256과 아카이브의 `recording/source/`, `source.patch`로 고정했다. 최종 공개 커밋은 이 소스와 분석 결과를 함께 담으며, 기존 manifest의 기준 커밋을 사후에 덮어쓰지 않는다.

- [후보 고정 기록](frozen-candidate.json), [9개 후보 탐색](tuning.json), [호스트 252회](host-summary.csv), [호스트 빌드·기존 출력 보존 검사](host-manifest.json).
- [보드 분석 JSON](summary.json), [보드 전체 시계열](board-series.csv.gz), [독립 시드 집계](host-aggregate.csv).
- [원시 아카이브](evidence.tar.gz), [파일별 크기·SHA-256](archive-inventory.json), [압축 해제·재분석 검증](verification.json).

아카이브에는 저장 입력 84개, 호스트 자료, 각 보드 실행의 원시 wire/CSV/콘솔/PERF, `.config`·펌웨어 이미지, 복구 기록, 소스 스냅샷, 빌드·검증 로그가 들어 있다. [package.py](package.py)는 모든 파일의 크기·해시를 검사하고 압축 해제한 기록을 다시 분석해 `summary.json`, `summary.csv`, `host-aggregate.csv`, `paired.csv`, `board-series.csv.gz`의 **5개 산출물이 바이트 동일한지** 확인한다. 실제 검증에서는 **514개 파일**, 압축 크기 **28,850,290 B**를 확인했으며 5개 재분석 산출물이 모두 바이트 동일했다. [검증 기록](verification.json)에 해시와 결과를 보관한다.

Python 3.12 환경에서 NumPy와 프로젝트 GUI/시험 의존성을 사용했다. 저장 기록 분석은 보드 없이 가능하다. 저장소의 해당 소스·파서와 함께 실행한다.

```sh
# 새 CT CTest와 독립 수치 기준
cmake -G Ninja -S fcc_app/tests/test_ekf_ct -B /tmp/radar-ct-tests
cmake --build /tmp/radar-ct-tests
ctest --test-dir /tmp/radar-ct-tests --output-on-failure
python docs/test-results/ct-ekf-2026-11-24/numeric_reference.py \
  --build /tmp/radar-ct-reference --output /tmp/radar-ct-reference/results.json

# 이 실험의 보관 경로에서 원시 기록 재분석·그림 생성
python docs/test-results/ct-ekf-2026-11-24/analyze.py \
  runs/ct-ekf-final-20261124 --output docs/test-results/ct-ekf-2026-11-24
python docs/test-results/ct-ekf-2026-11-24/plot.py \
  docs/test-results/ct-ekf-2026-11-24
python docs/test-results/ct-ekf-2026-11-24/package.py \
  runs/ct-ekf-final-20261124 --output docs/test-results/ct-ekf-2026-11-24

# 아카이브만 있는 경우 별도 디렉터리에서 재분석
mkdir -p /tmp/radar-ct-evidence
tar -xzf docs/test-results/ct-ekf-2026-11-24/evidence.tar.gz -C /tmp/radar-ct-evidence
python docs/test-results/ct-ekf-2026-11-24/analyze.py \
  /tmp/radar-ct-evidence/recording --output /tmp/radar-ct-evidence/analysis
```

펌웨어 선택·일반 빌드는 [추정기 설정](../../estimator-tuning.md)을 따른다. 보드 비교는 `perf.conf`와 이 폴더의 `configs/kf.conf`, `configs/ekf10000.conf`, `configs/ct.conf`를 각각 사용했다.

### 새 호스트·실보드 실험 실행

다음은 공개된 소스의 깨끗한 checkout에서 실행하는 예다. `runs/ekf-q-board-20261124`에는 앞선 Q 실험의 `plan.json`, `inputs/`, 기존 KF/CV `host-build/` 라이브러리가 있어야 한다. 원래 환경은 macOS/clang이며, 보관된 호스트 라이브러리는 플랫폼에 종속된다. `prepare.py`는 후보를 다시 선택하고 입력·빌드·출력 비교 기록을 **아직 없는 디렉터리**에 생성한다. 아래 `ct-ekf-repeat`는 새 이름의 예이며 기존 실험을 덮어쓰지 않는다.

```sh
# 저장소 루트, 프로젝트 Python 환경에서 실행
radar_repo="$PWD"
radar_recording="$radar_repo/runs/ct-ekf-repeat"
python docs/test-results/ct-ekf-2026-11-24/prepare.py \
  --prior runs/ekf-q-board-20261124 --output "$radar_recording"

# Zephyr workspace로 이동. 실제 설치 경로에 맞춘다.
cd ~/zephyrproject
source .venv/bin/activate

# 종료 시 복구할 일반 KF 이미지도 먼저 준비한다.
west build -p always -d "$radar_repo/build" -b stm32f746g_disco "$radar_repo/fcc_app"
west build -p always -d "$radar_repo/build_ct_kf" -b stm32f746g_disco "$radar_repo/fcc_app" -- \
  "-DEXTRA_CONF_FILE=$radar_repo/fcc_app/perf.conf;$radar_repo/docs/test-results/ct-ekf-2026-11-24/configs/kf.conf"
west build -p always -d "$radar_repo/build_ct_cv" -b stm32f746g_disco "$radar_repo/fcc_app" -- \
  "-DEXTRA_CONF_FILE=$radar_repo/fcc_app/perf.conf;$radar_repo/docs/test-results/ct-ekf-2026-11-24/configs/ekf10000.conf"
west build -p always -d "$radar_repo/build_ct_perf" -b stm32f746g_disco "$radar_repo/fcc_app" -- \
  "-DEXTRA_CONF_FILE=$radar_repo/fcc_app/perf.conf;$radar_repo/docs/test-results/ct-ekf-2026-11-24/configs/ct.conf" \
  -DCMAKE_C_FLAGS=-fstack-usage

cd "$radar_repo"
python docs/test-results/ct-ekf-2026-11-24/run_board.py "$radar_recording" \
  --data-port /dev/cu.usbserial-A5069RR4 --console-port /dev/cu.usbmodem11203 \
  --west "$HOME/zephyrproject/.venv/bin/west" --workspace "$HOME/zephyrproject"
python docs/test-results/ct-ekf-2026-11-24/analyze.py "$radar_recording" \
  --output "$radar_recording/analysis"
python docs/test-results/ct-ekf-2026-11-24/plot.py "$radar_recording/analysis"
```

포트 이름은 실제 연결에 맞추고 GUI 등 다른 UART 사용자를 종료한다. [run_board.py](run_board.py)는 입력과 설정을 검사하고 빌드 해시를 고정한 뒤, 18회마다 flash/reboot한다. 끝나면 일반 KF `build` 이미지를 복구하고 STATUS를 확인한다. `--preflight-only`를 추가하면 flash 없이 준비 조건만 검사한다. 기존 `board/` 기록은 덮어쓰지 않으므로 다시 실험할 때는 새 기록 디렉터리를 사용한다. 이 명령의 새 실행 결과는 위에 공개한 2026-11-24 기록과 별개다.

## 남은 범위

실제 레이더 입력, 가속/감속·좌우 반전·가변 선회율, 탐지 누락, 장시간 부하, IMM/SR/UD 비교는 이번 범위 밖이다. 고정 선회 경로의 host 84입력과 보드 6입력 조건을 확인한 결과이며, 이 합성 시나리오만으로 제품용 모델이나 게이트 크기를 확정하지 않는다.
