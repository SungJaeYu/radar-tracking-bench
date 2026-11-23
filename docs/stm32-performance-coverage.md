# STM32 성능 판정과 검증 범위

2026-11-23. PC 지연과 STM32 지연을 분리하되 기존 한계를 늘리지 않는다.
계측 추가로 실행 비용·메모리가 늘어나므로 새 PERF 이미지의 결과로 검증한다.

## 판정 계약

| 결과 | 의미 |
|---|---|
| `board_internal` | 실제 적용된 입력에서 아래 보드 내부 관측·자원 기준 충족 여부 |
| `delivery` | 송신 입력/응답·순번·상태·RX/TX 개수의 일치 |
| `evidence` | 필수 검사·모든 요약·기록 보존·정상 이미지 복원이 완전한지 |
| `host_rtt` | PC write 직전→응답 read 직후의 호스트 경로 진단. p99≤20ms·최대≤100ms; STM32/릴리스 gate 제외 |
| `requested_load` | 요청 기간 전체와50Hz 예정 슬롯 수를 빠짐없이 제공했는지 |
| `board_qualification` | board_internal+delivery+evidence, **관측 부하 범위** |
| `requested_profile_qualification` | 위 결과에 requested_load까지 충족했는지 |
| `passed` | `board_qualification.status == passed`의 호환 boolean. 요청 부하·호스트 RTT는 별도 |

각 분류는 `passed/failed/inconclusive`다. 누락·빈 표본·중단은 통과가 아니다.
호스트 RTT 초과와 PC 미송신 슬롯만으로 보드 합격이나 v1.1.0 릴리스를 차단하지 않는다. 요청 프로파일 미충족은 입력원 검증 한계이며 [v1.1.1 PC 시험기 개선](https://github.com/SungJaeYu/radar-tracking-bench/issues/8)으로 관리한다. `passed=true`여도 요청 부하 검증이 미확정일 수 있으므로 `requested_profile_qualification`을 함께 읽는다.
이전 원시 결과를 새 정책으로 덮어쓰지 않는다. RTT 옵션도20/100ms보다 느슨하게 설정할 수 없다.
[현재 정책 정정과 종합 검토](review-2026-11-23.md).

예정 슬롯 전부 송신과 하드 실시간 주기 정확성은 다르다. 실제 송신률·최대 공백·건너뛴 슬롯도 보고한다.
호스트가 입력을 덜 제공하면 관측 부하의 보드 결과만 해석할 수 있으며, 요청한 부하 전체의 증거는 미확정이다.

판정 버전 `2026-11-23-host-input-v3`는 정상 부하 중 다음 입력 불연속을 별도로 처리한다.

- PC write 간격 ≥ 실행 PERF 이미지의 `CONFIG_RADAR_MEASUREMENT_TIMEOUT_MS` (현재1,000ms).
- 순방향 센서 시각 간격 > 펌웨어 예측 한계1,000ms. uint32 wrap은 허용하지만 중복·역행을 면제하지 않는다.

이 경우 실제 송신과 한계를 `host_input_interruption`에 남기고 시험을 중단한다.
연속 입력을 가정한 최종 평가를 완료하지 못했으므로 각 분류는 미확정에서 시작하며,
이미 관측한 위반은 실패로 우선한다. `run_completed=false`, `passed=false`이며
CLI도 성공으로 종료하지 않는다. 입력이 정상일 때의 설명되지 않는 RESET/거부는
기존 검사 대상이다. 호스트 write 시각은 물리 UART 도착 시각으로 해석하지 않는다.
[수정·회귀·저장 기록 재평가](test-results/host-input-verdict-2026-11-23/README.md)는
원래의 RESET 오분류를 미확정으로 정정했으며 새30분 실보드 합격 증거가 아니다.

최신 [실보드 재검증](test-results/host-input-retest-2026-11-23/README.md)은30분
관측 부하의 보드·전송·증거 검사를 통과했다. 호스트 슬롯943개 누락으로 요청50Hz
전체 부하는 미확정이다. 의도적인1.2초 호스트 정지의 중단 분류와 복원도 확인했다.

## 소프트웨어 계측 및 기준

RX 링 대기는 DWT cycle 차이를 스레드에서 ms로 올림 변환하며 나머지 지연은 보드 uptime의 정수ms 관측이다.20ms는 프로젝트의50Hz 처리 예산이며 인증된 deadline은 아니다.
정수ms 계측으로1ms 미만의 차이나 실제20.000ms 경계의 정확한 상한을 보장하지 않는다.

| 구간/자원 | 계측 | 판정/한계 |
|---|---|---|
| UART FIFO 읽기 후 링 저장→링 제거 | `rx_byte_wait` | 관측 최대≤20ms, 초과0; PC 송신 바이트 수와 표본 수 일치 |
| UART RX ISR 본문 | `rx_isr` min/mean/max ns | 유효 표본·일관성 필수; 마지막 원시 계측 게시/예외 진입·복귀 제외, WCET 기준 미정 |
| 바이트 파서 실행 | `rx_parser` min/mean/max ns | 송신 바이트 수와 표본 수 일치; queue/log 처리 제외, WCET 기준 미정 |
| 파서 완료→handler 시작 | `queue_wait` | 관측 최대≤20ms, 초과0 |
| handler 시작→TX 큐 제출 반환 | `processing` | 관측 최대≤20ms, 초과0 |
| 파서 완료→TX 큐 제출 반환 | `rx_to_submit` | 기존 관측 최대≤20ms 기준 유지 |
| predict/correct | 실행 min/mean/max ns | 유효하고 일관된 표본 필수; 인터럽트/선점 포함 가능, WCET 기준 미정 |
| TX 큐 제출→dequeue | `tx_queue_wait` | 관측 최대≤20ms, TX polling 완료 프레임 수와 일치 |
| TX dequeue→encode 및 모든 poll_out 반환 | `tx_poll` | 관측 최대≤20ms, 같은 완료 프레임 수와 일치 |
| 측정 파서 완료→해당 TRACK polling 반환 | `parsed_to_tx_poll` | 관측 최대≤20ms, 유효 측정 수와 일치; 센서 시각 대신 보드 origin 전달 |
| RX/TX 큐·전송 | 접수/거부/완료/encode 실패 | 정상 부하에서 거부·오류0, PC 수신 및 요청 수와 대조 |
| 스케줄러 부하 | 누적 non-idle/idle cycle 차분 | 연속5초 요약 구간의 비유휴≤80%;20% 여유를 새 프로젝트 정책으로 설정 |
| 앱 스택 | RX/TX1024B, handler2048B, main1024B | 관측 최소 여유 각각256/256/512/256B 이상(25%); 미조회는 미검증 |
| 정적 메모리 | ELF/linker FLASH·RAM 및 config | 구성별 사용량 기록; heap pool0인 현재 설정 확인. 임의의 메모리 성능 합격 기준을 만들지 않음 |
| 장시간 무결성 | 기록/응답/부팅/STATUS/요약 | 모든 입력 대응·무손실·오류0·부팅1회·연속 요약. 기간과 적용 부하를 명시 |

새 자원 정책은 측정 전에 정했으며, 기존 검사 제거 대신 여유 조건을 추가했다.
ISR·파서·필터 실행 분포를 얻었다고 WCET 요구를 만족한 것으로 판정하지 않는다.
일반/DEBUG 펌웨어에는 PERF 수집기가 없으며 별도로 빌드한다.
PERF RX 시각 배열은1KiB, ISR 원시 계측 배열은2KiB를 사용한다. 스케줄러 계측·로그에도 비용이 있다. ISR은 유한 버퍼에 DWT 원시 값을 게시하고 RX 스레드가 집계한다. 공용 collector는 스레드 전용 mutex로 보호하며 히스토그램 계산·snapshot 복사 중 애플리케이션 IRQ 잠금은 사용하지 않는다. 커널 mutex 내부의 짧은 임계구역까지 없어진 것은 아니다. [인터럽트 경로 점검](interrupt-context-audit.md).

모든 요약에 확장 필드가 있어야 하며 idle에서만0표본을 허용한다. 마지막 누적값만 보고 중간 로그 누락을 통과시키지 않는다.
ISR 계측 버퍼 유실 또는1초 이상 서비스 공백은 `rx_capture_lost`로 실패 처리한다. 모든 요약에 해당 필드가 필요하다.
오류·큐 포화·복원 실패는 원인 분류와 함께 남긴다. 비동기 기록 큐는1,024개로 제한하며, 저장 실패를 숨기거나 조용히 버리지 않는다.

## 아직 전체 성능 검증이라고 할 수 없는 부분

`full_coverage=false`와 다음 경계를 결과에 남긴다. 아래 항목은 자동 통과로 간주하지 않는다.

| 미검증 항목 | 필요한 추가 증거 |
|---|---|
| 물리 RX 도착→ISR 진입, 인터럽트 지연 | GPIO/타이머 capture 또는 추적 장비로 입력 경계와 ISR 대조 |
| 실제 마지막 UART stop bit까지 | 로직 분석기/하드웨어 전송 완료 시각; poll_out 반환만으로 대체 불가 |
| RX 전체 경로의 한 프레임 시작→TX 완료 | 첫 바이트 기준 상관관계 또는 외부 wire 측정; 각 구간 최대의 합을 실측값으로 주장하지 않음 |
| 엄밀한 WCET·실행 시간 요구 충족 | 먼저 요구 deadline·경로·최악 부하를 규정하고 독립 분석/계측 |
| ISR를 분리한 실제 CPU 점유율 | 인터럽트/스레드 추적; scheduler non-idle 통계와 구분 |
| 시스템 전체 스택 안전성 | logger/idle/interrupt 스택 등 포함한 추가 조사; 현재4개 앱 스택 표본으로 전체 안전을 주장하지 않음 |
| 정확한 주기 입력·최대 지속 처리율 | 결정적인 입력원과 부하 단계 시험; PC 요청50Hz만으로 상한 throughput을 주장하지 않음 |
| 전원/온도/클록·UART 하드웨어 장애 전 종류 | 정한 조건에서의 별도 하드웨어 시험; host mock과 큐 포화 시험으로 대체 불가 |

따라서 이 변경은 **계측한 소프트웨어 경로를 더 엄격히 검증하는 설정**이다.
모든 STM32 성능을 빠짐없이 검증 완료했다는 선언이 아니다.

구현: [runner](../fcc_app/tests/test_perf_monitor/board_check.py), [분류 판정](../pc_sim/perf_acceptance.py).
실행 증거: [초기 확장 시험과 CRC 중단](test-results/extended-perf-2026-11-23/) · [IRQ 보완 후300초 기록](test-results/irq-safe-perf-2026-11-23/README.md).
300초 실행은 관측 부하에서 보드 내부·전송·증거를 통과했으며, 예정 슬롯201개 누락으로 요청50Hz 검증은 미확정이다. 원시 기록의 이전 aggregate 판정은 보존하고 [현재 해석](review-2026-11-23.md)을 별도로 따른다. CRC0인 후속 실행은 이전 CRC 오류의 원인을 확정하지 않는다.
