# 확장 기동 정답 모델

구현 시작 2026-11-25, 검증 마무리 2026-11-26. 이번 변경은 PC의 정답 궤적·시나리오와 입력 파일 지원이다. 새 기동의 KF/CV/CT 정확도 비교·실보드 시험은 아직 수행하지 않았다. 기존 펌웨어·필터·Q/R/P·게이트는 변경하지 않았다.

## 프리셋

모두 초기 위치 `(east=0, north=1000 m)`에서 출발한다. 기본은 동쪽 출발이며 이름 앞에 `outbound_`를 붙이면 북쪽으로 출발한다. 10종 × 2방향 = 20개다. 초기 진행 방향만 바꾸며 나머지 시간·속도·선회 조건은 같다.

| 이름 | 운동 조건 | 기간 |
|---|---|---:|
| `straight_100` / `straight_200` / `straight_300` | 각각 100/200/300 m/s 직선 등속 | 60 s |
| `turn_1deg` | 200 m/s, 직선10초 → +1°/s로90° 선회 → 직선10초 | 110 s |
| `turn_2deg` | 같은 순서, +2°/s | 65 s |
| `turn_4deg` | 같은 순서, +4°/s | 42.5 s |
| `s_turn` | 200 m/s, 직선10초 → +2°/s20초 → −2°/s40초 → +2°/s20초 → 직선10초 | 100 s |
| `accel_decel_2` | 200 m/s10초 → +2 m/s²20초 → 240 m/s10초 → −2 m/s²20초 → 200 m/s10초 | 70 s |
| `accel_decel_5` | 위와 같은 순서, ±5 m/s²와 최고300 m/s | 70 s |
| `turn_rate_ramp` | 200 m/s, 직선10초 → 선회율0→4°/s10초 → 유지10초 → 4→0°/s10초 → 직선10초 | 50 s |

S자 선회율 반전은 순간 전환이다. 부드러운 반전 프리셋은 이번에 추가하지 않았지만 `MotionSegment.angular_acceleration_radps2`로 표현할 수 있다. ramp의 총 방향 변화는80°다. 항공기 roll·공력·고도·바람을 포함하는 비행역학 모델은 아니다.

## 운동 계산

`Target`은 위치·속도·선회율 외에 다음 두 값을 보관한다.

- `acceleration_mps2`: 진행 방향 속력의 변화율. 고정된 x축 또는 y축 가속도가 아니다.
- `angular_acceleration_radps2`: 시계방향 선회율의 변화율.

한 구간에서 `v(t)=v0+a*t`, `omega(t)=omega0+alpha*t`, 누적 방향 변화는 `omega0*t+alpha*t²/2`다. 끝 속도·선회율은 이 식으로 계산한다. 위치는 회전하는 속도를8점 Gauss-Legendre 적분으로 계산하며, 패널당 시간1초·위상 변화 상한0.25rad를 사용한다. 센서 표본은 내부 적분 패널 수와 무관하다.

가속도·각가속도가 모두0이면 기존 직선·등선회 계산을 그대로 사용한다. 속력은 음수가 될 수 없고, 가속 모델은 초기 속도 방향을 필요로 한다. 정지 상태에서 재출발하는 모델은 지원하지 않는다. 잘못된 dt·비유한 입력·음수 속력은 오류로 보고하며 해당 Target 갱신 전 상태를 유지한다.

`MotionSegment`는 시작 선회율과 두 가속도를 지정한다. 구간이 시작되면 세 값을 적용하며 다음 구간에서 다시 설정한다. 큰 dt도 구간 경계에서 분할한다. 위치·속도는 경계에서 이어지고 지정된 선회율은 순간 전환할 수 있다.

## CLI와 저장 호환성

```sh
source ~/zephyrproject/.venv/bin/activate

# 포트 없이 프레임 미리보기: --duration은 시나리오 전체 길이 이상으로 지정
python -m pc_sim simulate --scenario s_turn --duration 100 --dt .1 --noise 10 --azimuth-noise .01 --seed 6

# 새 입력 생성·검증: 이 명령은 보드를 열지 않는다
python -m pc_sim input generate runs/inputs/outbound-ramp-6 \
  --scenario outbound_turn_rate_ramp --duration 50 --dt .1 \
  --noise 10 --azimuth-noise .01 --seed 6
python -m pc_sim input verify runs/inputs/outbound-ramp-6
```

`simulate`의 기존 `--port` 송신 경로도 새 프리셋 이름을 인식한다. 다만 새 기동의 저장 입력 평가기는 후속 작업이며, 기존 `turn-noise`는 기존3구간 선회 전용으로 유지한다. 새 GUI 평가 프리셋은 이번 범위에 포함하지 않는다.

기존3개 단일 표적 시나리오는 schema1과 기존 운동 메타데이터 구조를 유지한다. 새20개 프리셋은 schema2로 초기 상태·각 구간에 두 가속도를 기록한다. 샘플·UART 프레임 구조는 그대로다. 현재 로더는 v1/v2 모두 지원하며, 이전 코드의 v1 전용 로더는 새 입력을 거부한다. 생성 입력은 요청 기간과 구간 전체 길이 중 짧은 쪽에서 종료하고 종료 시각 표본은 포함하지 않는다.

## 검증

전체 Python **1,091개**가 통과했다. 새 운동 시험33개는 `tests/simulation/test_maneuver_models.py`에 별도로 추가했다. [실행 로그](pytest.log) · [검증 기록](verification.json). 기존 시험 본문·기대값은 수정하지 않았다.

- 직선 등가속도의 해석해, 각가속도 위치의 독립50,000분할 중점 적분과 비교.
- 큰 dt와100개 작은 dt의 위치·속도·선회율 일치, 구간 경계 가속도 초기화, ramp 방향 변화80° 확인.
- 잘못된 dt·가속도, 음수 속력, 불완전·다운그레이드된 새 메타데이터 거부.
- 20개 프리셋 전체 길이·최종 속력·프레임 생성·저장/읽기 동등성 확인.
- 기존3개 시나리오의 정답·잡음·wire 전체 표본 해시가 변경 전 `d6f92bc`와 동일.
- 실제 CLI로 `outbound_turn_rate_ramp` 500개 표본을 생성하고 읽기 검증 완료.

[궤적 그림](trajectories.png) · [속력·선회율 변화](motion-schedules.png). 그림은 잡음 없는 PC 정답이며 추정기 결과가 아니다. 대표6조건과 두 출발 방향을 표시한다.

```sh
QT_QPA_PLATFORM=offscreen python -m pytest
python docs/test-results/maneuver-models-2026-11-25/plot.py
```
