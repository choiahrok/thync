# 설정과 외부 서비스 연결

[문서 목차](README.md) · [프로젝트 소개](../README.md)

개인 정보와 회사 관련 값은 저장소에 넣지 않고 `~/.thync/`에 둡니다. 위치는 환경 변수 `THYNC_HOME`으로 바꿀 수 있습니다. 설정 파일은 없어도 동작하며, 쓰려면 [config.example.json](../config.example.json)을 `~/.thync/config.json`으로 복사해 수정합니다.

## 설정 파일 만들기

저장소 루트에서 다음 명령을 실행한 뒤 `config.json`을 편집합니다.

```bash
install -d -m 700 "${THYNC_HOME:-$HOME/.thync}"
cp config.example.json "${THYNC_HOME:-$HOME/.thync}/config.json"
```

예제 파일의 회사 폴더·이메일·Jira 주소는 자신의 값으로 바꿉니다. 설정은 시작할 때 읽으므로 수정 후 서버를 재시작합니다.

## 설정 키

설정 파일을 생략했을 때의 기본값입니다. **예제 파일은 `claude_code`를 제외한 세 출처만 사용합니다.** 세션 로그도 읽으려면 `sources`에 직접 추가합니다.

```json
{
  "sources": ["claude_code", "github", "jira", "notion"]
}
```

| 키 | 뜻 | 기본값 |
| --- | --- | --- |
| `sources` | 읽을 출처. `claude_code`(세션 로그), `github`(내 커밋, 리뷰 요청, 내 PR), `jira`(나에게 배정된 티켓), `notion`(최근에 고친 페이지) | 네 가지 모두 |
| `company_roots` | 이 폴더 아래에서 시작한 세션은 회사 프로필이 됩니다. PR을 맡길 때 로컬 저장소를 찾는 위치이기도 합니다 | `[]` (세션은 모두 개인) |
| `jira_browse_url` | Jira 티켓 링크 앞부분 (예: `https://example.atlassian.net/browse/`). 티켓 정보를 받아 올 주소도 여기서 정합니다 | 없음 (링크 없음) |
| `jira_email` | Jira Cloud 계정 이메일. API 토큰과 함께 있으면 티켓 요약·상태·상위 이슈를 자동으로 받아 옵니다 | 없음 (`jira.json`을 손으로 채움) |
| `cards_dir` | 칸반 카드 파일을 둘 폴더. Obsidian vault 안 폴더를 지정해도 됩니다 | `<THYNC_HOME>/cards` (기본 `~/.thync/cards`) |
| `port` | 서버 포트 | `8765` |
| `reflex_skills` | 내 PR을 맡길 때 실행할 Claude Code 스킬 (`sent`) | `pr-review-watch` |
| `notion_user_id` | 이 Notion 사용자가 마지막으로 고친 페이지만 사용합니다 | 없음 (integration이 볼 수 있는 페이지 모두) |

## 저장 파일

`~/.thync/`에 생기는 파일은 다음과 같습니다. 폴더는 나만 읽을 수 있게(0700) 만듭니다.

| 파일 | 내용 |
| --- | --- |
| `config.json` | 직접 만드는 설정 파일 (선택) |
| `token` | 접근 토큰 |
| `jira.json` | Jira 티켓 요약과 에픽: `{"ABC-1": {"summary": "...", "status": "진행 중", "epic": "ABC-0", "epic_summary": "..."}}`. 자동 수집 시 배정 티켓은 약 5분, 발견한 키의 요약은 약 10분마다 갱신합니다. 인증 설정이 없으면 직접 작성합니다 |
| `jira_token` | Jira API 토큰 (선택). 환경 변수 `JIRA_API_TOKEN`으로 줘도 됩니다. `chmod 600`으로 둡니다 |
| `notion_token` | Notion integration 토큰 (선택). 환경 변수 `NOTION_TOKEN`으로 줘도 됩니다. `chmod 600`으로 둡니다 |
| `names.json` | 화면에서 바꾼 노드 이름 |
| `cards/*.md` | 칸반 카드 ([파일 형식](usage.md#칸반-카드-파일)) |
| `reflex.json` | Claude에게 맡긴 PR과 진행 상태 (tmux 세션 이름이나 리뷰 결과) |

## Jira와 Notion 연결

두 서비스에서 데이터를 읽기만 합니다. 토큰은 `~/.thync/`의 파일이나 환경 변수로만 받고, 저장소·로그·주소·화면에는 남기지 않습니다.

### Jira Cloud

1. <https://id.atlassian.com/manage-profile/security/api-tokens> 에서 API 토큰을 만듭니다.
2. `~/.thync/config.json`에 `jira_browse_url`(예: `https://example.atlassian.net/browse/`)과 `jira_email`(Atlassian 계정 이메일)을 넣습니다.
3. 토큰을 파일로 둡니다.

```bash
install -m 600 /dev/null "${THYNC_HOME:-$HOME/.thync}/jira_token"
cat > "${THYNC_HOME:-$HOME/.thync}/jira_token"
```

토큰을 붙여 넣고 `Enter`, `Ctrl+D`를 눌러 입력을 마칩니다. 환경 변수 `JIRA_API_TOKEN`이 있으면 파일보다 우선합니다.

서버는 약 5분마다 `assignee = currentUser() AND (statusCategory = "In Progress" OR updated >= -7d)`로 나에게 배정된 티켓을 받아 `jira.json`에 `mine: true`로 기록합니다. 진행 중인데 지금 손대지 않는 티켓은 백그라운드가 됩니다.

### Notion

1. <https://www.notion.so/profile/integrations> 에서 internal integration을 만들고, 권한은 "콘텐츠 읽기"만 부여합니다.
2. thync에 보일 페이지(또는 상위 페이지)의 `...` 메뉴에 있는 연결(Connections)에서 그 integration을 추가합니다. integration은 연결한 페이지만 볼 수 있습니다.
3. 토큰을 파일로 둡니다.

```bash
install -m 600 /dev/null "${THYNC_HOME:-$HOME/.thync}/notion_token"
cat > "${THYNC_HOME:-$HOME/.thync}/notion_token"
```

토큰을 붙여 넣고 `Enter`, `Ctrl+D`를 눌러 입력을 마칩니다. 환경 변수 `NOTION_TOKEN`이 있으면 파일보다 우선합니다.

여러 사람이 고치는 페이지라면 `notion_user_id`에 내 Notion 사용자 id를 넣어 내가 마지막으로 고친 페이지만 남깁니다. 페이지 제목에 Jira 키(예: `ABC-123`)가 있으면 그 티켓의 작업 단위에 포함됩니다.

토큰을 넣은 뒤에는 서버를 다시 시작합니다.

## 수집 주기와 범위

화면 갱신 주기와 외부 서비스 조회 주기는 다릅니다. 화면은 2초마다 데이터를 요청하지만, 외부 결과는 캐시해서 사용합니다.

| 출처 | 수집 방식과 범위 |
| --- | --- |
| GitHub | 백그라운드에서 1분마다 갱신을 시도하며, 조회 결과는 기본 120초 동안 재사용합니다. 내 커밋·push, 내 리뷰 요청, 내 PR을 읽습니다 |
| Jira | 배정 티켓은 약 5분, 그래프에서 발견한 키의 요약은 약 10분 간격으로 갱신합니다. 배정 티켓 검색은 최근 수정 순 최대 50개입니다 |
| Notion | 백그라운드에서 1분마다 갱신을 시도하며, 결과는 기본 120초 동안 재사용합니다. 최근 수정 순 최대 100개, `notion_user_id`가 있으면 최대 300개를 받아 필터링합니다 |
| Claude Code | 로컬 세션 로그에서 새로 추가된 줄을 이어 읽습니다. `sources`에서 제외하면 읽지 않습니다 |

`jira` 출처를 끄면 배정 티켓 수집을 멈춥니다. 다만 다른 출처에서 발견한 Jira 키의 요약 조회는 Jira 주소·이메일·토큰이 설정되어 있으면 계속 동작합니다. Jira API 조회 전체를 끄려면 해당 인증 설정도 제거하고 서버를 재시작합니다.
