# 추정기 선택과 R·EKF Q 설정

CV·CT의 예측·보정 연산 변경 전후 시간과 동일 입력에 대한 출력 검증은 [v1.2.1 후보 실보드 비교](analysis/ekf-timing-20261126/README.md)에 있다.

## 빌드 시 KF / CV-EKF / CT-EKF 선택

`Radar application settings → Tracking estimator`의 Kconfig choice로 하나를 선택한다.

| 설정 | 상태 / 모델 |
|---|---|
| `CONFIG_RADAR_ESTIMATOR_KF_CV=y` (기본) | 기존 거리·방위각 독립 CV KF |
| `CONFIG_RADAR_ESTIMATOR_EKF_CV=y` | Cartesian `[x, y, vx, vy]` CV, 극좌표 측정 보정 EKF |
| `CONFIG_RADAR_ESTIMATOR_EKF_CT=y` | Cartesian `[x, y, vx, vy, omega]` CT, 극좌표 측정 보정 EKF |

`track.c → estimator.h의 공통 API → 선택한 구현 → 필터` 경로로 실행한다.
`cmake/estimator.cmake`가 Kconfig 선택에 맞는 구현과 필터 소스를 한 쌍으로 연결한다.
`estimators/polar_cv_kf.c`, `estimators/cartesian_cv_ekf.c`, `estimators/cartesian_ct_ekf.c`는 같은 네 함수를 구현하며,
함수 본문에는 필터 선택 전처리기가 없다. `estimator.c`의 공통 전달 함수도 필요하지 않다.
상태 크기가 다르므로 `estimator_state.h`에서 선택한 필터의 상태를 구조체 내부에 보관한다.
이것은 빌드 시 교체이며 런타임 함수 포인터 테이블을 사용하지 않는다.
측정 프로토콜·TRACK 출력 단위·직사각형 게이트·hit/miss/timeout 정책은 공통이다.
구조체는 선택한 필터 상태를 직접 소유하므로 `track_predict_next`의 값 복사가 유지된다.

새 추정기를 추가할 때는 전용 상태 헤더와 공통 네 함수의 구현을 추가하고,
Kconfig choice·상태 헤더 선택·CMake 매핑에 등록한다. 추적 호출부는 수정하지 않는다.
초기화·예측·보정·공통 출력 단위 및 상태 값 복사 계약을 지켜야 한다.

Zephyr workspace에서 CV-EKF를 별도 디렉터리에 빌드한다. `<repo>`는 실제 절대 경로로 바꾼다.

```sh
west build -d <repo>/build_ekf -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=ekf.conf
west flash -d <repo>/build_ekf --runner openocd
```

`fcc_app/ekf.conf`가 CV-EKF를 선택한다. `build_ekf/zephyr/.config`에서 선택 결과를 확인한다.
기존 KF는 추가 설정 없이 별도 `build` 디렉터리에서 빌드한다. 같은 디렉터리의 캐시 설정을
바꿔 쓰기보다 추정기별 빌드를 분리한다. 빌드만으로 연결된 보드의 펌웨어가 바뀌지는 않는다.
GUI/CLI는 보드가 보낸 동일한 TRACK 형식을 사용하며 실행 중 필터를 바꾸지 않는다.

CT-EKF는 별도 설정과 빌드 디렉터리를 사용한다. 아래 설정은 CT의 잠정 기본값이며 실험 후보 설정과는 구분한다.

```sh
west build -d <repo>/build_ct -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=ekf_ct.conf
west flash -d <repo>/build_ct --runner openocd
```

CV-EKF와 CT-EKF의 초기 속도는 `(0, 0)`이다. 초기 P는 기존 극좌표 분산
`diag(25, 0.00121847, 10000, 0.03046174)`를 `[r, θ, r_dot, θ_dot]` 순서로 놓고,
첫 측정 위치와 0 속도에서의 Jacobian으로 `J P Jᵀ` 변환한다. 위치와 속도 각각의
x/y 상관항을 보존한다. R을 바꿔도 이 초기 P는 함께 바뀌지 않는다.
CV-EKF Q는 x/y 축별 독립 가속도 분산을 사용하며 Kconfig 기본값은 `100 (m/s²)²`다. 기존 polar KF의 각가속도 Q와
물리적 의미가 다르며, 최적 튜닝값이나 센서 보정값으로 간주하지 않는다.

출력은 `r=hypot(x,y)`, `θ=atan2(x,y)`이며 동쪽 x·북쪽 y·북쪽 기준 시계 방향 방위각이다.
속도는 반경/접선 방향으로 투영해 m/s·rad/s로 반환한다. 정확히 원점이면 정의할 수 없는
방위각·변화율에 0을 반환한다. 두 EKF의 보정은 원점 근처 또는 수치 실패 시 예측값을 보존한다.
현재 공통 correct API가 void이므로 해당 생략은 별도 보고되지 않으며 UPDATED/hit는 게이트
통과를 뜻한다. 원점 통과·수치 실패 보고 정책 개선은 별도 과제다.

## 구현 구조와 상태 저장

```text
tracking/
  estimator.h                       공통 API·출력 계약
  estimators/
    estimator_state.h               선택된 필터 상태를 직접 소유
    polar_cv_kf.c                    거리·방위 KF 두 개 연결
    cartesian_cv_ekf.c               Cartesian CV-EKF 연결·출력 변환
    cartesian_ct_ekf.c               Cartesian CT-EKF 연결·출력 변환
    filters/
      kf_cv_1d.c / .h                1차원 CV KF 계산
      ekf_cv_2d.c / .h               2차원 CV EKF 계산
      ekf_ct_2d.c / .h               2차원 CT EKF 계산
```

1D/2D는 공간 차원이며 상태 원소 수가 아니다. KF는 `[value, rate]` 두 상태,
CV-EKF는 `[x, y, vx, vy]` 네 상태, CT-EKF는 여기에 `omega`를 더한 다섯 상태를 사용한다. 연결 코드는 Kconfig와 초기 튜닝을,
필터 코드는 수치 계산을 담당한다. 필터 계산 코드는 Kconfig에 의존하지 않는다.
이는 공통 계약 아래 필터를 멤버로 보유하는 합성(composition) 구조다.

모든 필터가 소유형 `struct matrix covariance`를 사용하며 KF의 활성 크기는 2×2,
CV-EKF는 4×4, CT-EKF는 5×5다. `init`에 전달한 초기 행렬은 복사하므로 호출자의 지역 변수 수명에
의존하지 않는다. KF 초기화도 네 scalar 인자 대신 `const struct matrix *`를 받는다.
고정 KF 초기 공분산 두 개는 함수 내부 `static const`에 보관하며, 필터별 가변 공분산에는 복사한다.
기존 KF의 전개된 예측·보정 계산식과 연산 순서는 유지하고 `matrix_get/set`으로 접근한다.
KF의 공분산 보정 방식을 Joseph으로 변경한 것은 아니다.

긴 입력 ASSERT는 각 필터 파일 아래의 private 검사 함수로 분리한다. `__ASSERT_ON=0`에서는
검사 함수와 호출 모두 제외한다. 수치 실패 시 예측값을 보존하는 실제 오류 처리는 항상 유지한다.

공통 matrix의 기본 저장 용량은 최대 4×4다. CT를 선택한 target에서만 `MATRIX_MAX_ROWS=5U`,
`MATRIX_MAX_COLUMNS=5U`를 모든 translation unit에 함께 적용한다. 기존 KF/CV target은 최대 4×4를
유지하며, KF는 활성 원소 네 개 외에도 저장 공간을 보유한다. 용량은 빌드 시 정해지고
동적 할당이나 외부 버퍼 포인터가 없다. 서로 다른 용량으로 컴파일된 행렬을 혼용하지 않는다.

## 측정 잡음 R

거리와 방위의 측정 잡음 **분산 R**을 Kconfig에서 설정한다. 초기 공분산 P, 과정 잡음 Q, 게이트와 추적 상태 전이 정책은 별개이며 R 변경으로 함께 바뀌지 않는다. 기본값은 기존 필터와 동일하다.

| 설정 | 단위 | 기본값 | 필터에 전달되는 R |
|---|---|---:|---:|
| `CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED` | m² | 25 | 25 m² (σ=5m) |
| `CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9` | 10⁻⁹ rad² | 1218470 | 0.00121847 rad² (σ≈2°) |

두 값은 양의 정수다. 방위 단위는 **10⁻⁹ rad²이며 (나노라디안)²가 아니다**. 거리 R의 설정 해상도는 1m²다. 표준편차 σ를 입력하려면 먼저 제곱한다. 방위는 rad로 변환한 뒤 제곱하고 10⁹을 곱한다.

예: 거리 σ=30m, 방위 σ=0.03rad를 가정한 실험용 `r.conf`:

```conf
CONFIG_RADAR_RANGE_MEASUREMENT_VARIANCE_M_SQUARED=900
CONFIG_RADAR_AZIMUTH_MEASUREMENT_VARIANCE_RAD_SQUARED_SCALED_1E9=900000
```

Zephyr workspace에서 별도 빌드 디렉터리와 추가 설정을 사용한다. 경로는 실제 절대 경로로 바꾼다.

```sh
west build -d <repo>/build_r_trial -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=<absolute-path>/r.conf
```

`build_r_trial/zephyr/.config`에서 두 설정을 확인한다. 빌드만으로 보드 설정은 바뀌지 않으며 별도 flash가 필요하다. 원래 빌드는 추가 설정 없이 독립된 디렉터리에 유지한다. Kconfig는 빌드 시 설정이므로 실행 중 명령으로 R을 바꾸지는 않는다.

## CV-EKF 과정 잡음 Q

`CONFIG_RADAR_EKF_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH`는 CV-EKF를 선택했을 때만
활성화된다. 기본값 `100`, 정수 범위 `0..2147483647`, 단위는 **m²/s⁴ = (m/s²)²**다.
가속도 표준편차가 아니라 분산이며 x/y 축에 같은 값을 독립적으로 적용한다.
Q 행렬의 모든 원소를 이 값으로 채우는 것이 아니다. 각 축의 `[위치, 속도]` 블록은 다음과 같다.

```text
Q_axis = q × [ dt⁴/4  dt³/2 ]
             [ dt³/2  dt²   ]
```

`dt`는 초 단위다. `q=0`은 과정 잡음의 추가를 끄며 기존 공분산의 예측 전파는 계속된다.
연결 계층이 설정을 필터 인자로 전달하며, 필터 핵심 계산은 Kconfig에 의존하지 않는다.
polar KF의 Q·초기 P·R·게이트는 이 설정으로 바뀌지 않는다. 큰 정수는 float로 변환되므로
상위 범위에서 정수 1 단위의 구분까지 보장하지 않는다.

예를 들어 별도 `q.conf`에서 EKF와 실험값을 함께 선택한다.

```conf
CONFIG_RADAR_ESTIMATOR_EKF_CV=y
CONFIG_RADAR_EKF_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH=10000
```

```sh
west build -d <repo>/build_ekf_q_trial -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=<absolute-path>/q.conf
```

생성된 `.config`를 확인하고 보드 실행이 필요할 때 해당 디렉터리로 별도 flash한다.
이 값은 실행 중 GUI/CLI argument로 변경되지 않는다. 공통 `prj.conf`에 EKF 전용 Q를
무조건 넣으면 KF 선택 시 의존성 경고가 발생할 수 있으므로 별도 실험 설정을 사용한다.

[2026-11-24 host Q 탐색](test-results/ekf-q-2026-11-24/README.md)은 기존 실보드와 같은
두 저장 입력에서 Q 12값을 비교했다. 이후 `10000·30000`을 고정해 [독립 시드·이탈 선회·실보드 비교](test-results/ekf-q-board-2026-11-24/README.md)를 완료했다. host336회, 주 실보드44회와 별도 게이트 진단2회의 근거를 남겼다. 후보의 순위는 잡음·seed에 따라 달랐고 기본값은 `100`을 유지한다.

## CT-EKF의 선회율·과정 잡음 설정

상태 `[x, y, vx, vy, omega]`에서 x는 동쪽, y는 북쪽이며 양의 omega는 시계방향이다.
omega 단위는 rad/s다. 초기 omega는 0이고 참값 선회율을 주입하지 않는다. 초기 공분산의
4×4 부분은 위 CV-EKF와 같고, omega 분산만 독립적으로 추가한다.

CT 선택 시에만 다음 Kconfig 항목이 활성화된다. 값은 모두 **분산**이다.

| 설정 | 정수 기본값 | 필터에 전달되는 값·단위 |
|---|---:|---|
| `CONFIG_RADAR_CT_ACCELERATION_VARIANCE_M_SQUARED_PER_S_FOURTH` | 100 | `q_acc=100` m²/s⁴ |
| `CONFIG_RADAR_CT_ANGULAR_ACCELERATION_VARIANCE_RAD_SQUARED_PER_S_FOURTH_SCALED_1E9` | 100000 | `q_alpha=0.0001` rad²/s⁴ |
| `CONFIG_RADAR_CT_INITIAL_TURN_RATE_VARIANCE_RAD_SQUARED_PER_S_SQUARED_SCALED_1E9` | 10000000 | `P_omega=0.01` rad²/s² |

과정 잡음 두 값은 0 이상이고, 초기 omega 분산은 양수다. 스케일된 정수는 10⁹으로 나누며,
`10⁻⁹ rad²` 단위는 `(10⁻⁹ rad)²`가 아니다. CT는 다음 이산 가산 잡음을 적용한다.

```text
G = [[dt²/2, 0,     0 ],
     [0,     dt²/2, 0 ],
     [dt,    0,     0 ],
     [0,     dt,    0 ],
     [0,     0,     dt]]
Q = G diag(q_acc, q_acc, q_alpha) Gᵀ
```

각가속도 잡음은 다음 omega에 더해진다. 같은 시간 간격의 원호 안에서 각가속도를 적분한 모델은 아니다.
상태 평균은 일정 선회율 원호를 사용하며, 0 근처의 선회율은 급수로 계산한다. 보정은 각도 잔차
정규화와 Joseph 공분산식을 사용한다. [정확한 상태식·수치 검증](test-results/ct-ekf-2026-11-24/README.md).

[CT 호스트 비교](test-results/ct-ekf-2026-11-24/README.md)는 original seed42의 두 입력으로 후보 9개를
탐색하여 `q_acc=100`, **`q_alpha=0.01`**, `P_omega=0.01`을 고정했다. 실험 후보의 q_alpha는
잠정 Kconfig 기본값 0.0001과 다르다. [별도 실험 설정](test-results/ct-ekf-2026-11-24/configs/ct.conf)을
사용하며, 기본 KF 선택과 기존 CV 기본값을 바꾸지 않는다.

같은 저장 입력 84개 × KF/CV/CT의 호스트 252회에서 유효 coverage 100%, 게이트 거부·LOST 0을
확인했다. 기존 KF/CV 168회는 이전 라이브러리 출력과 바이트 단위로 같았다. 독립 시드 80조건 중
74조건에서 CT 위치 RMSE가 CV 후보보다 작았으나 멀어지는 경로의 강한 잡음 seed6에서는 더 컸다.
실보드 18회에서 13,590개 입력이 모두 대응했고 게이트 거부·LOST·STATUS 오류는 0이었다.
일반 KF를 복구했다. CT의 handler 최소 미사용 스택은 784 B였으며, 관측 실행시간·스택은
이번 고정 경로의 결과다. 추가 기동·장시간 부하 검증은 별도다.

## 비교 방법

현재 기본값의 첫 KF/EKF 실보드 비교와 독립 NumPy 대조는 [2026-11-24 결과](history/hardware-test-2026-11-24-kf-ekf.md)에 있다. 초기 직선에서의 EKF 개선과 선회에서의 오차 증가를 함께 기록했으며, 이 결과에 맞춰 Q/R이나 기존 시험 조건을 변경하지 않았다.

- 같은 저장 입력을 모든 R 조합에 사용하고, 거리·방위 R을 독립적으로 바꾼다.
- 거리 RMSE(m), 방위 RMSE(rad), 위치 RMSE(m)를 구분한다.
- 초기 확정 시간, 연속 게이트 거부, LOST, 재시작, 유효 표본 수를 함께 기록한다.
- STARTED 후 워밍업을 제외한 오차만 보면 초기 상실을 놓칠 수 있다. 초기 구간과 전체 유효 구간의 오차도 별도로 기록한다. 유효 구간 오차에는 LOST/EMPTY의 무효 추정값이 포함되지 않는다.
- R을 잡음 분산과 같게 설정했다고 전체 추적 성능이 최적이 되는 것은 아니다. 고정된 P·Q, 움직임 모델, 게이트와 함께 평가한다.
- 같은 시드로 선택한 후보의 성능은 탐색 결과다. 새 시드·다른 기동·실제 보드 검증과 구분한다.

실험별 `.conf`, 원시 기록, 집계와 실행 코드 스냅샷은 로컬 `runs/`에 보관한다. 기존 테스트 시나리오를 변경하지 않고 별도 R 설정 테스트로 기본값 보존과 설정 반영을 검사한다.

## VS Code include 경로

KF, CV-EKF, CT-EKF 빌드는 서로 다른 소스와 행렬 용량을 compile database에 넣는다. 각 빌드에 `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`을 지정하고, 로컬 `.vscode/c_cpp_properties.json`의 `compileCommands`에 실제로 생성한 빌드의 경로를 포함한다. 아래는 `build`, `build_ekf`, `build_ct`를 사용한 예다.

```json
"compileCommands": [
  "${workspaceFolder}/build/compile_commands.json",
  "${workspaceFolder}/build_ekf/compile_commands.json",
  "${workspaceFolder}/build_ct/compile_commands.json"
]
```

기존 PERF/debug database가 있으면 유지한다. Kconfig·소스 경로를 바꾼 뒤 해당 빌드를 갱신해야 생성 헤더와 compiler flags도 반영된다. `.vscode`는 로컬 설정이므로 Git에 올리지 않는다. CT 파일도 CT target의 database를 사용해야 5×5 정의가 일치한다. database 등록과 VS Code 화면 진단 확인은 별도 검증이다.
