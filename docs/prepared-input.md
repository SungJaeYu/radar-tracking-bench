# 사전 생성 시험 입력

2D 단일 표적의 정답·측정값·센서 시각·완성 프레임을 시험 전에 생성하고 파일로 보관한다. 같은 파일을 읽으면 같은 순서와 바이트를 재사용할 수 있다. 입력 모듈은 **오프라인 생성·저장·검증·읽기**를 담당한다. `turn-noise`는 저장한 직선→선회→직선 입력의 UART 재생·보고 수집을 지원한다. 모든 입력용 공통 재생기, lockstep, 시험 후 일괄 송수신 기록 저장은 아직 구현하지 않았다.

## 실행

저장소 루트에서 Python 3.10 이상으로 실행한다. 프로젝트의 Python 3.12 가상환경을 사용할 수 있으며 추가 패키지는 필요 없다.

```sh
source ~/zephyrproject/.venv/bin/activate

# 직진 → 선회 → 직진 전체 입력. 시나리오 종료 약75.49초에서 끝난다.
python -m pc_sim input generate runs/inputs/turn-42 \
  --scenario straight_turn_straight --duration 80 --dt 0.02 \
  --noise 10 --azimuth-noise 0.01 --seed 42

# 파일 내용·해시·프레임을 검증한다. 입력을 다시 생성하지 않는다.
python -m pc_sim input verify runs/inputs/turn-42

# 50 Hz ×30분 규모의 연속 선회 입력:90,000샘플
python -m pc_sim input generate runs/inputs/long-turn-42 \
  --scenario single_turn --duration 1800 --dt 0.02 --seed 42
```

`runs/`는 Git 제외 경로다. 기존 디렉터리를 덮어쓰지 않으므로 다시 생성할 때는 새 이름을 사용한다. 명령은 시리얼 포트를 열거나 보드에 INIT/측정을 보내지 않는다.

| 옵션 | 의미 |
|---|---|
| `--scenario` | 기존3종 + [확장 기동20종](test-results/maneuver-models-2026-11-25/README.md): 직선·선회강도·S자·가감속·선회율변화 |
| `--duration` | 요청한 센서 시간 길이(s). 구간 시나리오는 자체 종료 시각까지 |
| `--dt` | 센서 샘플 간격(s), 최소0.001s. 기본0.02s |
| `--noise` | 거리 잡음 표준편차(m), 기본10 |
| `--azimuth-noise` | 방위각 잡음 표준편차(rad), 기본0.01 |
| `--pd` | 검출 확률0..1, 기본1. 센서 거리 밖에서도 측정이 없다 |
| `--seed` | 난수 seed, 기본42 |

단일 표적·클러터0만 지원한다. 기존 `targets.py`의 운동/센서 모델과 `protocol.py`의 인코더를 사용한다. `single_turn`은 TAS200m/s·뱅크30도 조건이며 기체 전체 비행역학 모사가 아니다. 도플러 잡음의 난수 소비도 기존 센서 모델과 같게 유지하지만 현재 UART payload에는 도플러가 없다.

## 파일과 단위

`metadata.json`에는 형식 버전, 요청/유효 기간, 샘플 수, 설정, 초기 표적 상태, 운동 구간, 센서 설정, 코드 출처와 해시를 저장한다. `samples.jsonl`은 한 줄에 센서 시점 하나를 저장한다.

| 필드 | 의미 |
|---|---|
| `index`, `timestamp_ms` | 0부터 시작하는 순번과 센서 시각. `round(index × dt_s ×1000)` |
| `truth_x_m`, `truth_y_m` | 정답 위치: 동쪽/북쪽(m) |
| `truth_vx_mps`, `truth_vy_mps` | 동쪽/북쪽 속도(m/s) |
| `truth_range_m`, `truth_azimuth_rad` | 정답 거리와 북쪽 기준 시계방향 방위각 |
| `measured_range_m`, `measured_azimuth_rad` | 센서 모델의 잡음 측정값, 전송 양자화 전 |
| `wire_range_m`, `wire_azimuth_sc` | 실제 payload의 정수 거리(m)와 int32 semicircle |
| `frame_hex` | CRC를 포함한15바이트 측정 프레임의30자리 hex |

검출이 없으면 정답·시각은 남기고 측정/전송 필드5개를 `null`로 저장한다. 유효한 측정을 인코딩할 수 없으면 생성에 실패한다. 기존 센서의 잡음 거리0 하한 처리는 유지되며, 검출된0m 측정은 wire 최소 거리1m를 만족하지 않아 실패한다.

실제 PC 송신·수신 시각과 보드 uptime은 이 파일에 없다. 종료 시각 미만의 센서 격자만 생성하며 끝점이나 INIT 프레임을 추가하지 않는다. 다음 재생 단계에서 INIT과 응답 기록을 별도로 처리해야 한다.

## 읽기와 변경 감지

1. 완료 manifest와 형식 버전·필수 필드·유한 수치를 검사한다.
2. 메타데이터의 정규화된 JSON SHA256과 샘플 파일의 바이트 SHA256을 확인한다.
3. 순번·샘플 수·센서 격자, 정답 직교/극좌표 일치, 측정과 payload/CRC 일치를 확인한다.
4. 검증된 파일에서 읽은 원래 프레임을 반환한다. 시나리오나 잡음을 다시 실행하지 않는다.

메타데이터의 공백·키 순서만 바뀌면 정규화된 내용은 같으므로 허용한다. 샘플 파일은 공백까지 바이트 단위로 검사한다. 해시는 우발적 손상 감지용이며 데이터와 해시를 함께 고치는 행위에 대한 인증은 아니다. 저장 당시의 소스 해시는 출처 정보다. 현재 코드와 출처 해시가 달라도 저장된 입력은 재생 기준으로 사용할 수 있다.

샘플 파일을 닫은 뒤 완료 manifest를 기록한다. 중단·저장 실패 시 남은 파일은 삭제하지 않지만 정상 데이터로 읽지 않는다. 디스크의 전원 장애까지 보장하는 트랜잭션 저장은 아니다.

Python에서 사용할 때:

```python
from pc_sim.storage.prepared_storage import load_input

prepared = load_input('runs/inputs/turn-42')
for sample in prepared.samples:
    if sample.frame is not None:
        frame = sample.frame  # Validated original bytes for a future replay sender.
```

## 자원 한도와 검증

- 최대180,000샘플을 생성·읽기 전에 확인한다. 이 한도는 바이트 단위 메모리 보증이 아니다.
- 메타데이터는64KiB, JSONL 한 줄은4KiB 이내다. 읽은 입력은 메모리에 보관한다.
- 기존 송신기와 직선·선회 프레임을 비교하고 seed 재현성, 검출 누락, 구간 종료, 범위 오류, 저장/읽기 완전 일치, 파일 변경, 재계산된 해시 뒤의 잘못된 payload, 불완전 저장을 시험한다.
- 90,000샘플의 오프라인 저장·읽기를 확인했다. JSONL은 약37.45MB이며 프레임 자체의1.35MB와 구분한다. 프로세스 메모리와 실행 시간은 환경에 따라 달라진다.

```sh
python -m pytest tests/simulation/test_prepared_input.py tests/storage/test_prepared_storage.py
```

실보드 실행은 아래 `turn-noise` 재생기에서 저장 프레임을 보내고 대응 TRACK의 sensor timestamp 및 STATUS를 확인한다. 현재 오프라인 결과는 보드 처리 성능·무누락50Hz 송신·새 필터 정확도를 검증한 것이 아니다.

## 직선 → 선회 → 직선의 잡음 입력

이슈 #10의 첫 입력 조건은 기존 센서 모델과 사전 생성 기능을 사용한다.
무잡음 대조군과 잡음 입력은 같은 궤적·10 Hz 센서 시각·seed 42를 사용한다.
잡음 입력은 거리 표준편차 10 m, 방위각 표준편차 0.01 rad(약 0.573°)다.
이는 첫 비교 조건이며 약·중·강 잡음이나 정확도 합격 기준을 정의한 것은 아니다.

```sh
python -m pc_sim input generate runs/inputs/turn-reference-42 --scenario straight_turn_straight --duration 80 --dt 0.1 --noise 0 --azimuth-noise 0 --seed 42
python -m pc_sim input generate runs/inputs/turn-noisy-42 --scenario straight_turn_straight --duration 80 --dt 0.1 --noise 10 --azimuth-noise 0.01 --seed 42
python -m pc_sim input verify runs/inputs/turn-noisy-42
```

출력 폴더가 이미 있으면 덮어쓰지 않으므로 다른 폴더 이름을 사용한다.
실제 궤적은 동쪽 직진 10초 → 우측 90° 선회 약55.487초 → 남쪽 직진 10초다.
80초 요청은 전체 궤적 약75.487초에 맞춰 종료되며 입력은 각각755개다.
`metadata.json`에는 단위가 포함된 설정·초기 표적·기동 구간·소스 식별값이,
`samples.jsonl`에는 정답 좌표/속도·정답 거리/방위각·잡음 측정값·wire 값·프레임이 저장된다.
무잡음이어도 wire 정수 변환에 따른 양자화는 별개로 존재한다.

이 명령은 입력 생성·검증만 수행하며 UART 송신이나 보드 추정 결과 수집은 하지 않는다.
보드 실행은 `python -m pc_sim turn-noise --port PORT --input runs/inputs/turn-noisy-42`로 진행한다. GUI Tests의 `Turn + noise`도 같은 실행기를 사용하며 기본 조건의 입력을 생성·보존한다. 위치 오차는 전체·선회 전·선회·선회 후로 평가한다.

## 확장 기동 입력

새 기동은 schema2로 가속도(m/s²)·각가속도(rad/s²)를 기록한다. 기존 입력은 schema1을 유지하며 현재 로더는 둘 다 읽는다. 샘플·wire 형식은 변경하지 않았다. [기동별 설정·CLI·정답 그래프](test-results/maneuver-models-2026-11-25/README.md). 새 기동의 필터 비교·실보드 평가와 GUI 프리셋 연결은 별도 후속 작업이다.
