# 호스트 입력 판정 수정 후 실보드 재검증

**후속 상태:** 이 문서는 당시 실행과 판단의 기록이다. [최종 v1.1.0 범위](../../release-v1.1.0.md)에서는 PC 미송신을 STM32 릴리스 차단 조건으로 사용하지 않는다. 시한 경과 sleep은 [후속 수정·60초 검증](../host-pacing-fix-2026-11-23/README.md)에서 보완했다. 원시 결과와 당시 readiness JSON은 변경하지 않았다.

2026-11-23, `feat/tracking-benchmark`, 기준 커밋 `20f069f` 위 작업본.
판정 버전 `2026-11-23-host-input-v3`.

**30분 관측 부하에서 보드 내부·전송·증거 검사를 통과했다.** 호스트가 예정
90,000개 중943개 슬롯을 놓쳐, 요청한 정확한50Hz 전체 부하 검증은 미확정이다.
의도적인 호스트 정지 시험에서는 새 중단 분류와 정상 이미지 복원을 확인했다.
v1.1.0 완료 선언·커밋·푸시·main 병합·태그는 수행하지 않았다.

## 실행 범위와 재현 자료

- 정상/PERF 증분 빌드 모두 `ninja: no work to do.`로 현재 소스와 일치했다.
- 직전 전체 실보드 회귀 이후 변경된 소스는 PC 시험기·판정기와 해당 Python
  테스트4개뿐이다. 이번에는 제품/판정 코드를 수정하지 않았다.
- [소스 해시137개](source-sha256.json)를 시작/종료 시 대조해 변경0을 확인했다.
  [사전 점검](preflight.json)에 포트·이미지 해시·소스 차이를 기록했다.
- 기존 Python924개+subtest9개와 기능·복구·C 회귀는 일치하는 소스의 이전
  증거를 재사용했다. 이번에 다시 실행한 것으로 표기하지 않는다.
- 실보드 실행은 짧은 PERF 확인, 1,800초 부하, 제어된 호스트 정지3개다.
  데이터 포트는 `/dev/cu.usbserial-A5069RR4`, 콘솔은 `/dev/cu.usbmodem11203`이다.
- 첫 샌드박스 시도는 콘솔 열기에서 `Operation not permitted`로 중단되어
  PERF flash/보드 시험을 시작하지 못했다. finally의 복원 접근도 차단됐다.
  [환경 접근 실패 원본](perf-smoke/results.json)을 보존하고 권한 적용 후
  별도 폴더에서 실행했다. 이를 STM32 동작 실패로 해석하지 않는다.

각 실행 폴더에 명령 인자에 해당하는 metadata, 두 config, ELF 해시, runner와
판정기 snapshot, 원시 wire/CSV/콘솔, PERF 요약, 복원 로그와 STATUS를 저장했다.

## 실제 결과

| 실행 | 관측 부하 보드 판정 | 요청 부하 | 주요 결과 |
|---|---|---|---|
| [10초 smoke와 복구](perf-smoke-board/results.json) | 통과 | 슬롯27개 누락으로 미확정 | 유효 측정476개, TRACK481개, STATUS11개, 오류0 |
| [30분 부하](perf-load/results.json) | 통과 | 슬롯943개 누락으로 미확정 | 측정89,057개 모두 대응, TRACK89,059개, STATUS1,801/1,801 |
| [의도적인 호스트 정지](controlled-host-gap/results.json) | 의도대로 미확정 | 미확정 | 정상 입력을 제공하지 못한 이유를 기록, 보드 실패 예외 없음, CLI exit1 |

30분 실행 시간은1,800.000211초, 실제 평균은49.476105Hz다. TRACK에는 INIT와
부하 종료 후 무수신 timeout의 입력 없는 보고2개가 포함된다. 모든 입력 대응,
순번, STATUS, RX/TX 개수 검사를 통과했다. STATUS8개 오류 카운터, 큐 거부,
TX 인코딩 실패, 계측 유실은0이다. 요약362개와 기록 이벤트378,944개가 보존됐고
기록 큐 enqueue/write 개수가 일치했다.

| 보드 관측 지연 구간 | 최대 | 한계 |
|---|---:|---:|
| RX 바이트 링 대기 | 2ms | 20ms |
| handler 큐 대기 | 2ms | 20ms |
| handler 처리 | 4ms | 20ms |
| RX 파서 완료→TX 제출 | 4ms | 20ms |
| TX 큐 대기 | 9ms | 20ms |
| TX dequeue→polling 반환 | 5ms | 20ms |
| RX 파서 완료→TX polling 반환 | 14ms | 20ms |

모든 구간의20ms 초과는0이다. 스케줄러 구간 비유휴 최대는25.323019%로80% 이하,
스택 최소 여유는 RX736/handler1,360/TX672/main496바이트로 각각
256/512/256/256바이트 기준을 충족했다. 이는 소프트웨어 관측 범위이며 물리
UART 도착/마지막 stop bit, 정확한 ISR 기여도, WCET 또는 전체 스택 안전성 증명은 아니다.

호스트 송신 간격 최대는604.072ms, RTT p99는11.279ms, 최대는659.311ms였다.
RTT 최대100ms 진단 한도는 초과했지만 STM32 합격/릴리스 gate에 넣지 않았다.
전체26개 check 중 이 호스트 진단1개만 false이며, 보드 내부·전송·증거 분류는
모두 통과했다. 슬롯943개는 별도의 요청 부하를 미확정으로 남긴다.

## 중단 분류의 실보드 확인

[재현 스크립트](controlled_host_gap.py)는 자신이 생성한 시험 프로세스만
측정100개 이상 기록한 뒤 `SIGSTOP`/`SIGCONT`로 정지·재개했다. 펌웨어나
사용자 프로세스에는 변경을 가하지 않았다. 요청 정지는1.2초였고 신호 사이
실측 간격은1.201710초였다.

새 guard는 PC write 간격1,213.196ms와 센서 간격1,200ms를 감지했다.
`host_input_interruption`에 두 원인을 저장하고 `run_completed=false`,
`passed=false`, `board_qualification=inconclusive`로 종료했다.
`failure`와 `restore_failure`는 모두 null이다. [검증7조건](controlled-host-gap-check.json)이 통과했다.

중단 직전 송신을 기록한 뒤 즉시 종료하므로 마지막 입력 응답/timeout RESET까지
수집한 실행은 아니다. 이 짧은 실행의 요약은 idle1개뿐이므로 성능 합격 증거로
취급하지 않는다. 확인한 것은 실제 호스트 정지에 대한 분류와 종료/복원 동작이다.
정상 이미지 복원 후 [STATUS8개 카운터0](controlled-host-gap/restored-status.json)을 확인했다.

## 독립 대조와 남은 범위

기존 [원시 기록 재검사 도구](../extended-perf-2026-11-23/audit.py)로 wire→CSV,
콘솔→PERF JSON, 저장된 버전의 판정기→results를 다시 대조했다. 세 실행 모두
일치했다: [smoke](perf-smoke-board/audit.json), [30분](perf-load/audit.json),
[호스트 정지](controlled-host-gap/audit.json). 재검사 통과가 미확정 부하를 합격으로 바꾸지는 않는다.

[v1.1.0 완료 점검](release-readiness.json)의 남은 항목은 요청한50Hz 전체 입력
조건 검증이다. 보드의 관측30분 처리는 통과했으며, 이번 실행에서 보드 실패가
확인됐기 때문에 릴리스를 보류하는 것은 아니다. 입력 누락 없이 해당 조건을
제공하고 검증한 증거가 아직 없다. 이전 CRC2건의 원인도 이번 CRC0 결과만으로
해결됐다고 단정하지 않는다.

[이전 전체 기능·복구 실보드 결과](../final-validation-2026-11-23/README.md)와
[판정 수정·Python 회귀](../host-input-verdict-2026-11-23/README.md)는 별도 이력이다.
합격 기준을 완화하거나 이전 결과를 덮어쓰지 않았다.
