# 문서 이미지 갱신

README와 EXPLAINER의 다이어그램은 GitHub 앱에서도 별도 Mermaid 렌더러 없이 표시하도록 PNG로 배포합니다. 그림의 원본은 `render_diagrams.py`이며, 시스템 구성·PC 왕복·펌웨어 내부 흐름을 각각 생성합니다.

저장소 루트에서 GUI 의존성이 설치된 Python 환경으로 실행합니다.

```sh
python -m pip install -r pc_sim/requirements-gui.txt
python tools/docs/render_diagrams.py
python tools/docs/render_diagrams.py --lang en
python tools/docs/capture_gui.py
```

- 다이어그램: `docs/images/system-overview.png`, `pc-board-flow.png`, `firmware-flow.png`.
- 영문 다이어그램: 같은 이름의 `.en.png` 파일. `--lang en`은 `diagram-labels.en.json`의 영문 라벨을 사용하고 한국어 PNG를 덮어쓰지 않습니다. 라벨을 수정할 때 해당 언어의 PNG도 다시 생성합니다.
- GUI 캡처: `docs/images/radar-gui-preview.png`, `radar-gui-track-preview.png`.
- 캡처는 실제 `MainWindow`와 `SessionWorker`를 Qt offscreen으로 실행합니다. 1440×900 화면을 2배 해상도로 저장합니다.
- 미리보기 설정: 초기 거리1000m, 변화율−10m/s, 방위각15°, 거리 잡음σ5m, 10Hz. 약11초간 생성 후 중지하고 설정·TRACK 탭을 캡처합니다. 호스트 실행 시각에 따라 표본 시각은 달라질 수 있습니다.
- UART 포트를 열거나 보드 응답을 주입하지 않습니다. 보드 추정값이 비어 있는지 확인합니다. 저장 경로 표시는 저장소 기준 `runs/`로 설정하고 CSV 기록은 끈 상태입니다.

생성 후 글자·선 겹침, 잘림, 실제 구현과 설명의 일치를 확인합니다. 문서만 갱신하는 작업이며 실보드 검증을 대신하지 않습니다. 날짜별 시험 문서의 과거 GUI 캡처는 덮어쓰지 않습니다.

## v1.1.0 영어 GUI

2026-11-23 미리보기 PNG를 영어 UI로 갱신했다. 실제 UART 캡처는
`docs/test-results/release-v1.1.0-2026-11-23/gui_check.py`로 별도 실행하며,
`docs/images/radar-gui-board.png`에 보드 TRACK 화면을 저장한다.
이 증거용 스크립트의 포트·경로를 확인하고 모든 다른 송신기를 종료한 뒤 실행한다.
[시험 조건과 실제 결과](../../docs/history/hardware-test-2026-11-23-v1.1.0.md)를 함께 읽는다.

## 저장된 실보드 기록의 분석과 영상

`analyze_board_results.py`는 2026-11-23의 30분 성능 기록과 별도 선회 시험을 읽어 PNG/SVG 5종, CSV/JSON, 한국어 Markdown·HTML 보고서를 만든다. 원본 수치와 대응 개수·분위수·RMSE를 대조하고 입력 파일의 SHA-256을 기록한다.

`render_gui_video.py`는 별도 GUI 세션의 CSV를 기존 Qt 화면에 공급해 40초 무음 H.264 MP4를 만든다. `SessionWorker`나 시리얼 포트는 열지 않는다. 화면 확대·재생 표시만 적용하며 제품 GUI 코드는 바꾸지 않는다. 재생 영상은 새 실보드 시험 증거가 아니다.

기존 GUI 의존성에 Matplotlib와 imageio-ffmpeg가 필요하다. 현재 영상의 글꼴 경로는 macOS Arial을 사용하므로 다른 운영체제에서는 `font()`의 경로를 변경해야 한다. 저장소 루트에서 다음과 같이 별도 임시 경로에 설치·실행할 수 있다.

```sh
python -m pip install --target /private/tmp/radar-report-deps matplotlib==3.11.2 imageio-ffmpeg==0.8.1
PYTHONPATH=/private/tmp/radar-report-deps python tools/docs/analyze_board_results.py
PYTHONPATH=/private/tmp/radar-report-deps python tools/docs/render_gui_video.py
```

산출물: [분석·영상 디렉터리](../../docs/analysis/2026-11-23/README.md). `--preview-only`는 영상 대신 표본 PNG만 생성하며 `video-provenance.json`을 preview 상태로 갱신하므로, 최종 배포 전에 옵션 없이 다시 실행한다. CSV/JSON에는 계산값과 원본 집계값을 저장하고 HTML 표는 소수 셋째 자리까지 표시한다.
