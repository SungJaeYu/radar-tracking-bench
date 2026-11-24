# Python 테스트

저장소 루트에서 실행한다. `pytest.ini`의 `testpaths = tests`가 하위 폴더까지 수집한다.

```sh
source ~/zephyrproject/.venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m pytest

# 특정 영역만 실행
python -m pytest tests/simulation tests/storage
python -m pytest tests/transport
python -m pytest tests/cli
python -m pytest tests/firmware
```

| 폴더 | 검증 대상 |
|---|---|
| `transport/` | 프로토콜·프레임 파서·TRACK 해석·Python/C wire 상호운용 |
| `simulation/` | 표적 운동·시나리오·샘플/표시 모델·이상치·사전 생성 입력 |
| `storage/` | 세션 CSV·비동기 기록·사전 생성 입력 파일 검증 |
| `evaluation/` | 시나리오 평가·STM32 성능 판정 정책 |
| `ui/` | Qt GUI·작업자 동작; GUI 선택 의존성 필요 |
| `cli/` | 통합 진입점·역할별 모듈 명령·송신/STATUS·종료 코드·선택 의존성 분리 |
| `firmware/` | 펌웨어 assert·계측 경계의 host C probe와 보드 시험기의 Python 로직 |

이 pytest 실행은 실제 보드를 flash하거나 실제 UART 포트를 사용하지 않는다.
`firmware/`와 wire 상호운용 일부는 host C 컴파일러를 사용한다.
Zephyr 펌웨어 빌드·CMake/CTest·실보드 시험은 `fcc_app/tests/`의 각 안내를 따른다.

파일을 직접 지정할 때는 새 경로를 사용한다. 예:

```sh
python -m pytest tests/simulation/test_prepared_input.py tests/storage/test_prepared_storage.py
```
