# 보드 성능 계측

`perf.conf`는 V1 지속 부하 시험에 사용한 별도 펌웨어 구성이다. 시간·큐·송신 통계와 스택 여유를 수집하며 main이 5초마다 ST-Link 콘솔에 누적 `PERF` 요약을 출력한다. UART 프로토콜과 STATUS_REPORT는 변경하지 않는다. 일반·debug 빌드에는 계측 코드가 포함되지 않는다.

## 현재 성능 기준 — 2026-11-23 확장

보드 내부, 전송 무결성, 증거 완전성, 호스트 RTT, 요청 부하 충족을 독립 판정한다.
`passed`는 `board_qualification`의 통과 여부로, 보드 내부·전송·증거가 모두 통과해야 참이다. 적용 범위는 **관측 부하**다.
`requested_profile_qualification`은 여기에 요청 부하 충족까지 요구한다. 호스트 RTT와 PC 미송신은 STM32 합격·릴리스 차단 기준에 포함하지 않는다. 실제 제공한 입력의 전달·응답·보드 지연·오류 기준은 유지한다. PC 송신기 개선은 [v1.1.1 #8](https://github.com/SungJaeYu/radar-tracking-bench/issues/8) 범위다.
필수 관측 누락은 `inconclusive`이며 통과가 아니다. [정책 정정·전체 검토](review-2026-11-23.md).
정확한 필드·한계·미검증 영역은 [STM32 성능 검증 범위](stm32-performance-coverage.md)를 따른다.

기존 보드 지연20ms와 호스트 RTT 진단 한도 p99≤20ms·최대≤100ms를 유지한다. RTT 옵션으로 진단 한도를 더 엄격하게 설정할 수 있지만 늘릴 수 없다.
RX 링 대기, ISR·파서 실행, TX 큐 대기·polling 및 파서 완료→TX polling 반환을 추가 수집한다.
스케줄러 비유휴는 연속 요약 구간에서80% 이하, RX/TX/handler/main 스택 최소 여유는 각 할당량의25% 이상이어야 한다.
이 자원 여유 정책은 새 시험 전에 정한 프로젝트 기준이며 인증된 운용 요구사항은 아니다.

50Hz 예정 슬롯을 빠뜨렸거나 요청 기간을 채우지 못하면 `requested_load`는 미확정이다.
관측 부하에서 보드 내부가 통과해도 요청50Hz 전체 검증으로 승격하지 않는다.
송신 간격은 계속 기록하며, 슬롯 수 충족도 정확한 물리 주기를 보장하지 않는다.
PC RTT는 write 직전→TRACK을 담은 read 직후로 USB·UART·호스트 대기를 포함한다.

현재 판정 버전은 `2026-11-23-host-input-v3`다. 정상 부하 송신 중 PC write 간격이
실행 이미지의 `CONFIG_RADAR_MEASUREMENT_TIMEOUT_MS` 이상이거나, 순방향 센서 시각
간격이 펌웨어 예측 한계1,000ms를 초과하면 `host_input_interruption`으로 종료한다.
실제 송신을 먼저 기록하고 정상 연속 입력을 전제한 응답 검사를 중단한다.
이때 최종 평가와 요청 부하는 미확정이며, 이미 관측된 CRC·큐·지연·자원·기록·복원
위반은 계속 실패다. RESET을 일괄 허용하거나 합격 한계를 늘리지 않는다.
[실제 입력 공백·정상 RESET 오분류의 수정과 저장 기록 재평가](test-results/host-input-verdict-2026-11-23/README.md)는
새 실보드 시험이 아니다. 후속30분 관측 부하는 통과했고, 누락 없는 요청50Hz 전체 입력만 미확정으로 남는다.

2026-11-19의 송신 간격·평균률을 참고 통계로 취급한 정책과 당시 원시 결과는 이력으로 보존한다.
[V1 기준선](hardware-test-2026-11-19-performance.md)은 당시 조건의 결과이며 새 확장 계측의 증거가 아니다.

## 2026-11-23 재검증

최신 판정 수정 후1,800초 실행은 측정89,057개 모두 대응·STATUS 오류0으로 관측
부하의 보드·전송·증거 검사를 통과했다. 보드 지연 최대는 구간별2~14ms, 스케줄러
구간 비유휴 최대25.323%, 네 앱 스택 여유는 기준 이상이다. 호스트 슬롯943개
누락으로 요청50Hz 전체 부하는 미확정이며, RTT 최대659.311ms는 진단 전용이다.
제어된1.2초 호스트 정지에서도 미확정 분류와 정상 이미지 복원을 확인했다.
[최신 실보드 실행·독립 대조](test-results/host-input-retest-2026-11-23/README.md).

이하 기록은 각 이전 실행의 조건과 당시 판정을 보존한다.

30분 요청50Hz·실제49.7733Hz에서 측정89,592개 모두 대응했으나, PC RTT 최대220.246ms가100ms 기준을 초과해 **당시 정책에서 실패**했다. p99는9.080ms로20ms 기준 이내였다. 이 원본 판정은 보존하며 현재 정책의 STM32 불합격·릴리스 차단 근거로 사용하지 않는다. 보드 내부 RX→TX 제출 최대1ms·큐 거부0과 PC 전체 왕복 지연을 구분한다. 호스트 송신 공백과 겹친 지연 꼬리의 원인은 아직 확정하지 않았다. [전체 수치·원시 기록·조사 경계](hardware-test-2026-11-23-v1.1.0.md).

확장 계측 후 장시간 재시험과 짧은 재시험 모두 보드 수신 CRC 오류로 중단됐다. 이 오류를 호스트 영향으로 단정하지 않는다. [추가 증거와 판정 보완](test-results/extended-perf-2026-11-23/README.md).

IRQ 경로 보완 후300초 실행은 유효 측정14,802개 모두 대응·보드 CRC0으로 관측 부하의 보드 내부·전송·증거 검사를 통과했다. 요청15,000슬롯 중201개를 건너뛰어 요청50Hz 검증은 미확정이다. PC RTT p99 14.727ms·최대328.516ms는 별도 호스트 진단 결과다. 이 실행은30분 새 확장 계측 검증이나 이전 CRC 오류의 원인 확정을 뜻하지 않는다. [수정 당시 원시 기록](test-results/irq-safe-perf-2026-11-23/README.md)과 [현재 판정 해석](review-2026-11-23.md)을 구분한다.

현재 정책으로 실행한60초 확인은 유효 측정2,981개 모두 대응·CRC/STATUS 오류0으로 보드 내부·전송·증거를 통과했다. 최대 PC RTT117.529ms의 진단 초과는 보드 합격에 영향을 주지 않으며, 예정 슬롯22개 누락은 요청 부하 검증을 미확정으로 남긴다. [현재 검토·새 실행 원본](review-2026-11-23.md).

## ISR·임계구역 보완

확장 계측의 ISR 집계와 IRQ 차단 중 시각 조회·통계 갱신을 제거했다. ISR은 DWT 원시 값을 유한 버퍼에 게시하고 RX 스레드가 집계한다. 공용 collector의 spinlock도 thread-only mutex로 바꿔 히스토그램 계산과 전체 통계 복사 동안 애플리케이션이 IRQ를 잠그지 않는다. mutex 취득·해제 내부의 짧은 커널 임계구역까지 없앴다는 뜻은 아니다. 계측 저장 공간 유실 또는1초 이상 서비스 공백은 sticky 실패이며 보드 기준·호스트 진단 한도는 유지한다. [전체 점검 결과](interrupt-context-audit.md). 수정 전 CRC 기록은 원인 확정 증거가 아니며 보존한다.

## 빌드와 원복

2026-11-23 기록 경로 변경: 성능 시험 도구는 UART 소유 스레드에서 송수신 시각을 찍고, 별도 기록 스레드가 세션 CSV·원문 콘솔 파일을 저장한다. 큐는1,024개 이벤트로 제한하며 포화·저장 오류는 증거 검사 실패다. 종료 시 받아 둔 기록을 비우고10초 이내 join하며 큐 전달/저장 개수를 결과에 남긴다. console 파싱과 wire 검증은 UART 스레드에 유지한다. 스레드 분리는 호스트 sleep·스케줄링 지연까지 제거하지 않으므로 RTT는 같은 진단 한도와 함께 계속 기록한다.

```sh
cd ~/zephyrproject
west build -d <repo>/build_perf -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=perf.conf -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
# 실제 측정할 때만 플래시한다.
west flash -d <repo>/build_perf --runner openocd
# 시험을 마친 뒤 일반 이미지를 다시 빌드하고 복원한다.
west build -d <repo>/build -b stm32f746g_disco <repo>/fcc_app -- -DEXTRA_CONF_FILE=
west flash -d <repo>/build --runner openocd
```

`<repo>`는 저장소의 절대 경로로 바꾼다. `debug.conf`, `log_stress.conf`, `transport_stress.conf`와 섞지 않는다. DEBUG 프레임 로그나 강제 소비 스레드 정지는 측정 부하 자체를 바꾼다.

| 설정 | 의미 |
|---|---|
| `CONFIG_RADAR_PERF_MONITOR=y` | collector·reporter와 호출 지점 활성화. LOG에 의존하며 스택 조회에 필요한 두 설정을 선택한다 |
| `CONFIG_INIT_STACKS=y` | 시작할 때 스택을 패턴으로 채워 사용 흔적을 조회할 수 있게 한다 |
| `CONFIG_THREAD_STACK_INFO=y` | 스레드 스택 범위 정보를 보관한다 |
| `CONFIG_RADAR_LOG_STRESS_TEST=n` | 합성 로그 폭주 제외 |
| `CONFIG_RADAR_TRANSPORT_STRESS_TEST=n` | RX/handler/TX 강제 정지 제외 |

최종 설정은 `build_perf/zephyr/.config`에서 확인한다. 현재 보드 구성의 kernel tick은 10,000Hz지만 `k_uptime_get()`으로 저장하는 계측 값의 단위는 정수 ms다. 1ms 미만 차이를 세밀하게 구분하지 못하며 이 지연 통계는 cycle 기반 실행 시간이나 CPU 점유율 측정이 아니다. 별도의 estimator 실행 시간은 아래 기준을 따른다.

## 시간 기준과 대상

```text
RX 파서 완료              handler process 진입           uart_tx_submit 반환
received_uptime_ms (t0)       k_uptime_get() (t1)              k_uptime_get() (t2)
        └──── queue_wait ──────┘
                                └──── processing ──────────┘
        └──────────────── rx_to_submit ───────────────────┘
```

- `queue_wait`: handler가 받은 **모든 MEAS_REPORT**의 `t1-t0`. 오래된/무효 측정도 포함한다. RX 큐에 들어오지 못한 프레임은 제외한다.
- `processing`: 해당 측정의 TRACK이 TX 큐에 **성공적으로 등록된 경우**의 `t2-t1`.
- `rx_to_submit`: 같은 성공 집합의 `t2-t0`. 게이트/시각 거부 결과도 TRACK을 성공 제출했다면 포함한다.
- `t0`는 기존 보드 RX 완료 시각이다. 첫/마지막 바이트 ISR 시각이나 센서 `input_timestamp_ms`가 아니다.
- `t2`는 송신 큐 제출 반환 직후, 제출 결과 로그 전에 기록한다. `uart_tx_submit()` 내부 계측 비용도 포함한다. UART 실제 전송·PC 수신까지의 지연은 아니다.
- 처리 시간에는 선점·대기와 계측 자체의 비용도 포함된다. 순수 필터 실행 시간이나 WCET라고 해석하지 않는다.

C의 시간 통계 타입은 `perf_latency_stats`이며, `sample_count`는 표본 수,
`histogram_counts`는 구간별 빈도, `over_budget_count`는 기준 초과 횟수다.
큐 통계는 `accepted_count`, `rejected_count`, `max_observed_depth`로 저장한다.
콘솔 필드 형식은 [로그 규칙](logging.md)을 따른다. 보드 검증 parser는 이전 로그도 읽고 JSON의 기존 키를 유지한다.

각 시간 통계는 `n`, `total_ms`, `max_ms`, `over_budget_count`, 히스토그램을 유지한다. 평균은 `total_ms / n`으로 계산하며 n=0이면 표본이 없다. 부팅 이후 누적값이고 5초 구간별 통계가 아니다.

히스토그램은 0..20ms 각각 한 구간과 **>20ms 구간 21**로 구성된다. 로그의 `p50_bin`, `p95_bin`, `p99_bin`은 nearest-rank 방식의 구간 번호다. 예를 들어 `p99_bin=21 max_ms=40`이면 p99는 **20ms 초과**, 관측 최대는 40ms라는 뜻이며 p99=21ms라는 뜻이 아니다. 초과 구간의 정확한 백분위가 필요하면 후속 시험에서 더 넓거나 세밀한 계측을 추가해야 한다. `over_budget_count`은 엄격한 `>20ms`이며 20ms는 포함하지 않는다.

## Estimator 실행 시간 — 2026-11-22

`CONFIG_RADAR_PERF_MONITOR`와 `CONFIG_TIMING_FUNCTIONS`가 모두 켜지면 `track.c`에서
`estimator_predict()`와 `estimator_correct()` 호출 전후의 timer cycle을 측정한다.
실제로 호출된 연산만 집계하므로 predict/correct 표본 수는 서로 다를 수 있다.
집계 함수와 로그 출력은 측정 구간 밖에 있으며, 구간 중 인터럽트·선점과 타이머 조회 비용은 포함될 수 있다.
순수 명령어 비용이나 WCET 보장값으로 해석하지 않는다.

`perf_execution_stats`는 부팅 이후 표본 수·cycle 합계·최소·최대를 유지한다.
reporter는 기존 snapshot에서 평균 cycle을 정수 나눗셈으로 계산한 뒤
Zephyr `timing_cycles_to_ns()`로 최소·평균·최대를 ns로 변환한다.
평균은 cycle 단위에서 먼저 소수 부분이 버려지며, ns 표기는 ns 단위의 측정 해상도를 뜻하지 않는다.

```text
PERF estimator_predict: n=0 status=no_samples
PERF estimator_correct: n=3 min_ns=100 mean_ns=200 max_ns=300
```

위 숫자는 출력 형식 예시이며 실측값이 아니다. board_check는 새 필드를 JSON과 원문 콘솔 로그에 보존하며, 실행 시간 필드가 없는 예전 로그도 파싱할 수 있다. 현재 확장 판정에서는 필수 필드 누락이 미확정이고, 유효한 표본 수와 min≤mean≤max의 일관성을 검사한다. ISR·파서·predict/correct 실행 시간의 WCET 상한은 아직 정하지 않았다. 5초마다 출력하지만 5초 구간별 통계가 아니다.
표본이 없으면 나눗셈을 하지 않는다. count 또는 합계가 넘치는 표본은 집계 전체를 변경하지 않고 제외한다.
타이밍 기능이 없는 구성에서는 자동 측정 hook이 꺼지고, 직접 기록한 표본은 `_cycles` 필드로 출력한다.
새 실행 시간 출력은 host 테스트·펌웨어 빌드와 [2026-11-22 STM32 smoke](hardware-test-2026-11-22-logging.md)에서 확인했다.
기존 11월 18~19일 부하 시험은 이 출력의 검증 증거가 아니다.

## 카운터·소유권·집계 범위

| 필드/로그 | 의미 |
|---|---|
| `measurements` | handler에 진입한 MEAS_REPORT 수 |
| `without_submit` | 측정 처리 종료까지 TRACK 제출 호출이 없던 수. stale·무효 payload·TRACK 인코딩 실패를 포함하며 세 원인은 기존 로그/STATUS로 구분 |
| `submit_failed` | 측정 TRACK의 `uart_tx_submit()` 실패 수. 성공 시간 분포에서 제외 |
| `invalid_time` | 음수·역행 보드 시각 때문에 시간 표본을 제외한 수. 정상 uptime 흐름에서는 0 기대 |
| `queue rx/tx accepted/rejected` | 유효 submit 인자의 큐 등록 성공/실패. RX는 모든 프레임 TYPE, TX는 STATUS·제어 TRACK까지 포함 |
| `observed_max_used` | 제출 직후 조회한 큐 점유 수의 최대. 소비자가 이미 꺼낼 수 있어 실제 최대 점유율의 하한 관측값 |
| `tx poll_completed` | 프레임의 모든 `uart_poll_out()` 호출을 마친 수. 상대 수신 ACK나 마지막 stop bit 완료가 아님 |
| `tx encode_failed` | TX 워커에서 wire 인코딩에 실패한 수 |
| `stack rx/handler/tx/main unused_bytes/min_unused_bytes` | 스택 패턴 검사에서 관측한 미사용 바이트와 조회한 값들의 최솟값. 조회 실패는 `status=unavailable error=<negative errno>`. 파서는 과거 `unavailable=<negative errno>` 형식도 읽고 저장 결과의 `unavailable` 키를 유지함 |

collector의 스레드 전용 `k_mutex`가 카운터·snapshot을 보호하며 ISR 호출은 assert로 거부한다. 집계·snapshot 복사는 IRQ 잠금 밖에서 수행한다. 잠금 안에서는 시계 조회·큐 API·스택 검사·로그를 실행하지 않는다. handler만 측정 begin/end를 호출하며 중첩 호출을 지원하지 않는다. 제출 여부와 무관하게 종료 지점에서 문맥을 해제한다. INIT/RESET·무수신 timeout의 입력 없는 TRACK은 측정 지연에 포함하지 않는다.

카운터는 UINT32_MAX에서 포화한다. 시간 통계는 count가 포화되면 합계·히스토그램·최대값을 함께 동결한다. 한 시간 표본도 UINT32_MAX ms로 제한하여 uint64 누적 합계가 넘치지 않게 한다. latency 집계 함수는 음수 입력을 내부에서 검사하여 assert하며, assert가 비활성화되어도 표본을 제외한다. INIT/RESET은 이 통계를 지우지 않는다. 새 run은 재부팅으로 시작한다.

통계 구조체는 한 번의 잠금으로 복사하지만 여러 단계의 이벤트는 서로 다른 순간에 기록된다. 입력·처리·송신이 진행 중일 때 카운터가 즉시 일치하지 않을 수 있다. 스택 검사는 snapshot 이후 별도 조회이며 동시에 실행 중인 스레드의 사용을 샘플링한다. 무손실·완전한 peak 검출이나 stack overflow 부재를 보장하지 않는다.

collector는 `src/diagnostics/perf_monitor.c/.h`, 출력·스택 조회는 `perf_reporter.c/.h`에 둔다. main은 `perf_reporter.h`의 `perf_reporter_log_summary()`를 호출한다. 별도 계측 스레드를 만들지 않고 기존 main 루프를 사용한다. 큰 출력용 snapshot은 main 스택 대신 reporter의 정적 저장소에 둔다. 로그 모듈 `radar_perf`는 고정 INFO다. 요약은 여러 LOG 호출이므로 다른 로그와 섞이거나 버퍼 포화 시 일부가 누락될 수 있다.

## 검증과 다음 보드 시험

host 사례와 실행 명령은 [성능 계측 테스트](../fcc_app/tests/test_perf_monitor/README.md)에 정리했다. 요구사항은 [REQ-PERF-001](requirements-traceability.md#spec-perf)로 추적한다.

1. `perf.conf`를 플래시하고 ST-Link 콘솔 원문을 저장한다. 처음에는 입력 없이 0 표본·RX/handler/TX/main 네 스택과 스케줄러 통계 조회 결과를 확인한다.
2. predict/correct의 무표본 출력과 정상 입력 후 표본 수·최소/평균/최대 ns를 확인한다. 짧은 정상 입력에서 queue_wait/processing/rx_to_submit 표본 증가, 20ms 초과 횟수, STATUS/TRACK PC 수신과 TX 집계를 대조한다.
3. INIT/RESET·무수신 timeout 보고가 측정 표본을 추가하지 않는지, 오래된/무효 입력·큐 실패가 각 카운터에 반영되는지 확인한다.
4. 별도 run에서 선언 부하(50Hz 측정·50Hz 결과·1Hz STATUS)를 30분 적용한다. 시작/종료 설정·baud·프레임 수·모든 누적 요약·RX STATUS·PC CSV를 함께 남긴다. 전체 기간의 예정 슬롯을 빠뜨렸으면 요청 부하 검증을 미확정으로 남긴다.
5. 송신 중단 후 큐가 비워진 구간의 통계를 비교한다. timeout 이벤트 TRACK 등 입력 없는 보고도 TX 프레임 수에 포함해 설명한다. 계측 로그 유실/타임스탬프 이상이 있으면 유효한 성능 증거로 단정하지 않는다.
6. 일반 이미지를 복원하고 기본 왕복을 확인한다.

계측 구현·host/빌드·실보드 관측은 확보했으며, 최신 구성의30분 관측 부하와 호스트 중단 분류도 실보드에서 확인했다. 요청50Hz 전체 입력은 슬롯943개 누락으로 미확정이다. 추가 보드 시험은 필요한 기간·부하·오류 조건을 명시하며 PC RTT 진단 초과나 PC 미송신만으로 STM32 재시험이나 릴리스 보류를 요구하지 않는다. [최신 실행과 남은 범위](test-results/host-input-retest-2026-11-23/README.md)를 따른다.
