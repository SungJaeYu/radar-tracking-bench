# 추정기 선택과 칼만 필터 측정 잡음 R 설정

## 빌드 시 KF / EKF 선택

`Radar application settings → Tracking estimator`의 Kconfig choice로 하나를 선택한다.

| 설정 | 상태 / 모델 |
|---|---|
| `CONFIG_RADAR_ESTIMATOR_KF_CV=y` (기본) | 기존 거리·방위각 독립 CV KF |
| `CONFIG_RADAR_ESTIMATOR_EKF_CV=y` | Cartesian `[x, y, vx, vy]` CV, 극좌표 측정 보정 EKF |

`track.c → estimator.h의 공통 API → 선택한 구현 → 필터` 경로로 실행한다.
`cmake/estimator.cmake`가 Kconfig 선택에 맞는 구현과 필터 소스를 한 쌍으로 연결한다.
`estimators/polar_cv_kf.c`와 `estimators/cartesian_cv_ekf.c`는 각각 같은 네 함수를 구현하며,
함수 본문에는 필터 선택 전처리기가 없다. `estimator.c`의 공통 전달 함수도 필요하지 않다.
상태 크기가 다르므로 `estimator_state.h`에서 선택한 필터의 상태를 구조체 내부에 보관한다.
이것은 빌드 시 교체이며 런타임 함수 포인터 테이블을 사용하지 않는다.
측정 프로토콜·TRACK 출력 단위·직사각형 게이트·hit/miss/timeout 정책은 공통이다.
구조체는 선택한 필터 상태를 직접 소유하므로 `track_predict_next`의 값 복사가 유지된다.

새 추정기를 추가할 때는 전용 상태 헤더와 공통 네 함수의 구현을 추가하고,
Kconfig choice·상태 헤더 선택·CMake 매핑에 등록한다. 추적 호출부는 수정하지 않는다.
초기화·예측·보정·공통 출력 단위 및 상태 값 복사 계약을 지켜야 한다.

Zephyr workspace에서 EKF를 별도 디렉터리에 빌드한다. `<repo>`는 실제 절대 경로로 바꾼다.

```sh
west build -d <repo>/build_ekf -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=ekf.conf
west flash -d <repo>/build_ekf --runner openocd
```

`fcc_app/ekf.conf`가 EKF를 선택한다. `build_ekf/zephyr/.config`에서 선택 결과를 확인한다.
기존 KF는 추가 설정 없이 별도 `build` 디렉터리에서 빌드한다. 같은 디렉터리의 캐시 설정을
바꿔 쓰기보다 두 빌드를 분리한다. 빌드만으로 연결된 보드의 펌웨어가 바뀌지는 않는다.
GUI/CLI는 보드가 보낸 동일한 TRACK 형식을 사용하며 실행 중 필터를 바꾸지 않는다.

EKF 초기 속도는 `(0, 0)`이다. 초기 P는 기존 극좌표 분산
`diag(25, 0.00121847, 10000, 0.03046174)`를 `[r, θ, r_dot, θ_dot]` 순서로 놓고,
첫 측정 위치와 0 속도에서의 Jacobian으로 `J P Jᵀ` 변환한다. 위치와 속도 각각의
x/y 상관항을 보존한다. R을 바꿔도 이 초기 P는 함께 바뀌지 않는다.
EKF Q는 x/y 축별 독립 가속도 분산 `100 (m/s²)²`를 사용한다. 기존 polar KF의 각가속도 Q와
물리적 의미가 다르며, 최적 튜닝값이나 센서 보정값으로 간주하지 않는다.

출력은 `r=hypot(x,y)`, `θ=atan2(x,y)`이며 동쪽 x·북쪽 y·북쪽 기준 시계 방향 방위각이다.
속도는 반경/접선 방향으로 투영해 m/s·rad/s로 반환한다. 정확히 원점이면 정의할 수 없는
방위각·변화율에 0을 반환한다. 기존 EKF 보정은 원점 근처 또는 수치 실패 시 예측값을 보존한다.
현재 공통 correct API가 void이므로 해당 생략은 별도 보고되지 않으며 UPDATED/hit는 게이트
통과를 뜻한다. 원점 통과·수치 실패 보고 정책 개선은 별도 과제다.

## 구현 구조와 상태 저장

```text
tracking/
  estimator.h                       공통 API·출력 계약
  estimators/
    estimator_state.h               선택된 필터 상태를 직접 소유
    polar_cv_kf.c                    거리·방위 KF 두 개 연결
    cartesian_cv_ekf.c               Cartesian EKF 연결·출력 변환
    filters/
      kf_cv_1d.c / .h                1차원 CV KF 계산
      ekf_cv_2d.c / .h               2차원 CV EKF 계산
```

1D/2D는 공간 차원이며 상태 원소 수가 아니다. KF는 `[value, rate]` 두 상태,
EKF는 `[x, y, vx, vy]` 네 상태를 사용한다. 연결 코드는 Kconfig와 초기 튜닝을,
필터 코드는 수치 계산을 담당한다. 필터 계산 코드는 Kconfig에 의존하지 않는다.
이는 공통 계약 아래 필터를 멤버로 보유하는 합성(composition) 구조다.

두 필터 모두 소유형 `struct matrix covariance`를 사용하며 KF는 활성 크기 2×2,
EKF는 4×4다. `init`에 전달한 초기 행렬은 복사하므로 호출자의 지역 변수 수명에
의존하지 않는다. KF 초기화도 네 scalar 인자 대신 `const struct matrix *`를 받는다.
고정 KF 초기 공분산 두 개는 함수 내부 `static const`에 보관하며, 필터별 가변 공분산에는 복사한다.
기존 KF의 전개된 예측·보정 계산식과 연산 순서는 유지하고 `matrix_get/set`으로 접근한다.
KF의 공분산 보정 방식을 Joseph으로 변경한 것은 아니다.

긴 입력 ASSERT는 각 필터 파일 아래의 private 검사 함수로 분리한다. `__ASSERT_ON=0`에서는
검사 함수와 호출 모두 제외한다. 수치 실패 시 예측값을 보존하는 실제 오류 처리는 항상 유지한다.

공통 matrix는 최대 4×4 고정 배열을 사용하므로 KF의 활성 원소 네 개 외에도 저장 공간을
보유한다. 메모리는 항상 정적으로 결정되며 동적 할당이나 외부 버퍼 포인터가 없다.

## 측정 잡음 R

거리와 방위의 측정 잡음 **분산 R**만 Kconfig에서 설정한다. 초기 공분산 P, 과정 잡음 Q, 게이트와 추적 상태 전이 정책은 별개이며 R 변경으로 함께 바뀌지 않는다. 기본값은 기존 필터와 동일하다.

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

## 비교 방법

- 같은 저장 입력을 모든 R 조합에 사용하고, 거리·방위 R을 독립적으로 바꾼다.
- 거리 RMSE(m), 방위 RMSE(rad), 위치 RMSE(m)를 구분한다.
- 초기 확정 시간, 연속 게이트 거부, LOST, 재시작, 유효 표본 수를 함께 기록한다.
- STARTED 후 워밍업을 제외한 오차만 보면 초기 상실을 놓칠 수 있다. 초기 구간과 전체 유효 구간의 오차도 별도로 기록한다. 유효 구간 오차에는 LOST/EMPTY의 무효 추정값이 포함되지 않는다.
- R을 잡음 분산과 같게 설정했다고 전체 추적 성능이 최적이 되는 것은 아니다. 고정된 P·Q, 움직임 모델, 게이트와 함께 평가한다.
- 같은 시드로 선택한 후보의 성능은 탐색 결과다. 새 시드·다른 기동·실제 보드 검증과 구분한다.

실험별 `.conf`, 원시 기록, 집계와 실행 코드 스냅샷은 로컬 `runs/`에 보관한다. 기존 테스트 시나리오를 변경하지 않고 별도 R 설정 테스트로 기본값 보존과 설정 반영을 검사한다.

## VS Code include 경로

KF와 EKF 빌드는 서로 다른 소스만 compile database에 넣는다. 두 빌드에 `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`을 지정하고, 로컬 `.vscode/c_cpp_properties.json`의 `compileCommands`에 다음 두 경로를 포함한다.

```json
"compileCommands": [
  "${workspaceFolder}/build/compile_commands.json",
  "${workspaceFolder}/build_ekf/compile_commands.json"
]
```

기존 PERF/debug database가 있으면 유지한다. Kconfig·소스 경로를 바꾼 뒤 해당 빌드를 갱신해야 생성 헤더와 compiler flags도 반영된다. `.vscode`는 로컬 설정이므로 Git에 올리지 않는다. 이번에는 두 구현의 현재 파일이 각각 올바른 database에 등록되는 것을 확인했으며, VS Code 화면 진단을 직접 확인한 결과는 아니다.
