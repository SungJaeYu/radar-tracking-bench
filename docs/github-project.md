# GitHub 작업 관리

저장소: [SungJaeYu/radar-tracking-bench](https://github.com/SungJaeYu/radar-tracking-bench) · [프로젝트 보드](https://github.com/users/SungJaeYu/projects/1).

표 보기와 **진행 현황** 보드를 사용한다. 상태는 Todo / In Progress / Done이다. 완료한 작업은 저장소 반영과 검증 후 Done으로 옮긴다.

| 범위 | 이슈 | 완료 조건 |
|---|---|---|
| v1.1.0 릴리스 | [#1](https://github.com/SungJaeYu/radar-tracking-bench/issues/1) | 관측 부하 STM32 검증, 문서, main 통합·태그 |
| GUI 영상·분석 | [#2](https://github.com/SungJaeYu/radar-tracking-bench/issues/2) | 무음 재생 영상·그래프·표·출처를 저장소에 게시 |
| v1.1.1 PC 시험기 | [#8](https://github.com/SungJaeYu/radar-tracking-bench/issues/8) | 입력 생략 없는 재생 정책·주기 설정·시간축 분리 검토와 검증 |
| 3D 1/4 | [#4](https://github.com/SungJaeYu/radar-tracking-bench/issues/4) | 좌표계·단위·측정 모델·2D 호환성 |
| 3D 2/4 | [#5](https://github.com/SungJaeYu/radar-tracking-bench/issues/5) | 고도·수직속도·3D 시나리오; #4 이후 |
| 3D 3/4 | [#6](https://github.com/SungJaeYu/radar-tracking-bench/issues/6) | 프로토콜·필터 확장; #4·#5 이후 |
| 3D 4/4 | [#7](https://github.com/SungJaeYu/radar-tracking-bench/issues/7) | GUI·3D 오차·실보드 검증; #5·#6 이후 |

PC 미송신은 STM32 불합격이나 v1.1.0 릴리스 차단 조건이 아니다. #8에서 호스트 개선으로 관리하며 정확한 주기·최대 처리율 검증과 관측 부하 합격을 구분한다.

과거 CRC 2건은 조치 후 비재현·해결 추정/원인 미확정 이력으로 [검토 문서](review-2026-11-23.md)에 근거와 가설을 보존한다. 사용자 요청에 따라 별도 이슈는 두지 않는다.

향후 큰 설계 변경은 사용자 검토 후 단계별로 진행한다. v1.1.1과 3D 구현은 이번 릴리스의 코드 변경 범위가 아니다.
