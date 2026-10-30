# brain-atlas 외부 코드 안내

[전체 문서 목차](../../docs/README.md) · [아키텍처](../../docs/architecture.md) · [프로젝트 소개](../../README.md)

## 출처와 라이선스

[colorpulse6/brain-atlas](https://github.com/colorpulse6/brain-atlas) 커밋 `81e237529af1b75f4a23e4cb472bc51110ef7b0f`(2026-10-02)에서 뇌 그래프를 그리는 Canvas2D 코드만 가져왔습니다. 라이선스는 MIT이고 원문은 [LICENSE](LICENSE)에 있습니다.

## 가져온 범위

뇌 그래프를 그리는 Canvas2D 코드만 포함합니다. 아래 항목은 가져오지 않았습니다.

| 제외 항목 | 파일 또는 범위 |
| --- | --- |
| Obsidian 의존 코드 | `main.ts`, `src/view.ts`, `src/adapter.ts`, `src/settings-tab.ts`, `src/diagnostics.ts` |
| WebGL 렌더러 | `src/gl/` |
| 노트 분류 | `src/classify.ts` |
| 데모·스타일·개발 설정 | 데모와 스타일, 빌드·테스트 설정 |

## thync에서 수정한 부분

thync에서 수정한 위치는 코드에 `thync:` 주석으로 표시했습니다.

| 파일 | 수정 내용 |
| --- | --- |
| [`src/renderer.ts`](src/renderer.ts) | 진행 중인 노드의 맥동과 후광, 더 밝은 뇌 윤곽 |
| [`src/cloud.ts`](src/cloud.ts), [`src/shape.ts`](src/shape.ts) | 뇌 표면 점 개수 1,400 → 2,600, 뇌간 아래의 짧은 척수 |
| [`src/overlay-labels.ts`](src/overlay-labels.ts), [`src/types.ts`](src/types.ts) | 작업 단위 제목(`clusterTitles`)과 제목이 겹치지 않도록 위치 조정 |
