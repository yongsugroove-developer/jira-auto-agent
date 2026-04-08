const FIELD_LABELS = {
  jira_base_url: "Jira Base URL",
  jira_email: "Jira Email",
  jira_api_token: "Jira API Token",
  jira_jql: "JQL",
  github_owner: "GitHub Owner",
  github_repo: "GitHub Repo",
  github_base_branch: "Base Branch",
  github_token: "GitHub Token",
  repo_mappings: "공간별 저장소 연결",
  local_repo_path: "Local Repo Path",
  branch_name: "Branch Name",
  commit_message: "Commit Message",
  codex_model: "Codex Model",
  codex_reasoning_effort: "Reasoning Effort",
  work_instruction: "작업 지시 상세",
  acceptance_criteria: "수용 기준",
  test_command: "로컬 테스트 명령",
  commit_checklist: "커밋 체크리스트",
  git_author_name: "Git Author Name",
  git_author_email: "Git Author Email",
  mapping_space_key: "Jira 공간 키",
  mapping_repo_owner: "GitHub owner",
  mapping_repo_name: "GitHub repo",
  mapping_base_branch: "기본 브랜치",
  mapping_local_repo_path: "로컬 저장소 경로",
  mapping_github_token: "공간 전용 GitHub Token",
  allow_auto_commit: "로컬 테스트 없이 자동 커밋 허용",
  enable_plan_review: "실행 전 계획 확인 사용",
};

const guideState = {
  guide: null,
  guidePromise: null,
  activeSectionId: null,
  activeStepId: null,
};

const jiraState = {
  selectedIssueDetail: null,
  issueDetailRequest: null,
  pendingIssueKey: null,
  expandedIssueKey: null,
  issueAccordionCollapsed: false,
  issueModalKey: null,
  backlogIssues: [],
  backlogInputType: "radio",
  backlogInputName: "selected_issue",
  backlogPageIndex: 0,
  backlogColumns: 1,
  backlogItemsPerPage: 1,
};

const workflowState = {
  pollTimer: null,
  activeRunId: null,
  resultPanelOpen: true,
  clarificationQuestions: [],
  clarificationAnswers: {},
  lastJiraCommentSync: null,
};

const repoMappingState = {
  items: [],
  editingIndex: null,
  editingDraft: null,
};

const configFlowState = {
  repoSuggested: false,
};

const workspaceState = {
  view: "prepare",
  backlogResizeTimer: null,
  shellHeightTimer: null,
  shellHeightRaf: 0,
  heightObserver: null,
  isTransitioning: false,
};

const DEFAULT_AUTOMATION_RESULT_HINT = "Codex 자동 작업을 실행하면 결과를 여기에 표시합니다.";

const VISIBLE_WORKFLOW_PHASES = new Set([
  "queued",
  "running",
  "branch_prepare",
  "branch_ready",
  "codex_start",
  "codex_turn",
  "codex_message",
  "codex_command",
  "stage_changes",
  "stage_ready",
  "commit_start",
  "commit_end",
  "codex_timeout",
  "completed",
  "failed",
]);
const WORKFLOW_PHASE_LABELS = {
  queued: "대기",
  running: "실행",
  completed: "완료",
  failed: "실패",
  branch_prepare: "브랜치 준비",
  branch_ready: "브랜치 준비 완료",
  codex_start: "Codex 시작",
  codex_turn: "Codex 진행",
  codex_message: "Codex 진행",
  codex_command: "명령 실행",
  codex_timeout: "Codex 시간 초과",
  stage_changes: "변경 수집",
  stage_ready: "변경 수집 완료",
  commit_start: "자동 커밋",
  commit_end: "자동 커밋 완료",
};

FIELD_LABELS.work_instruction = "작업 지시 상세";
FIELD_LABELS.acceptance_criteria = "수용 기준";
FIELD_LABELS.test_command = "참고용 로컬 테스트 명령";
FIELD_LABELS.commit_checklist = "커밋 체크리스트";

const MAX_VISIBLE_WORKFLOW_EVENTS = 8;
VISIBLE_WORKFLOW_PHASES.add("syntax_start");
VISIBLE_WORKFLOW_PHASES.add("syntax_end");
WORKFLOW_PHASE_LABELS.queued = "대기";
WORKFLOW_PHASE_LABELS.running = "실행";
WORKFLOW_PHASE_LABELS.completed = "완료";
WORKFLOW_PHASE_LABELS.failed = "실패";
WORKFLOW_PHASE_LABELS.branch_prepare = "브랜치 준비";
WORKFLOW_PHASE_LABELS.branch_ready = "브랜치 준비 완료";
WORKFLOW_PHASE_LABELS.codex_start = "Codex 시작";
WORKFLOW_PHASE_LABELS.codex_turn = "Codex 진행";
WORKFLOW_PHASE_LABELS.codex_message = "Codex 진행";
WORKFLOW_PHASE_LABELS.codex_command = "명령 실행";
WORKFLOW_PHASE_LABELS.stage_changes = "변경 수집";
WORKFLOW_PHASE_LABELS.stage_ready = "변경 수집 완료";
WORKFLOW_PHASE_LABELS.commit_start = "자동 커밋";
WORKFLOW_PHASE_LABELS.commit_end = "자동 커밋 완료";
WORKFLOW_PHASE_LABELS.codex_timeout = "Codex 시간 초과";
WORKFLOW_PHASE_LABELS.syntax_start = "문법 검사";
WORKFLOW_PHASE_LABELS.syntax_end = "문법 검사 완료";

function parseRepoMappingsText(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.split("|").map((part) => part.trim()))
    .filter((parts) => (parts.length === 5 || parts.length === 6) && parts.slice(0, 5).every(Boolean))
    .map((parts) => ({
      space_key: parts[0].toUpperCase(),
      repo_owner: parts[1],
      repo_name: parts[2],
      base_branch: parts[3],
      local_repo_path: parts[4],
      github_token: parts[5] || "",
      has_saved_token: false,
      clear_saved_token: false,
    }));
}

function serializeRepoMappings(items) {
  return (items || [])
    .map((item) => [
      String(item.space_key || "").trim(),
      String(item.repo_owner || "").trim(),
      String(item.repo_name || "").trim(),
      String(item.base_branch || "").trim(),
      String(item.local_repo_path || "").trim(),
    ].join("|"))
    .filter((line) => !line.includes("||"))
    .join("\n");
}

function repoMappingTokenSummary(item) {
  if (item.clear_saved_token) {
    return "공간 전용 GitHub Token 제거 예정";
  }
  if (item.github_token) {
    return "공간 전용 GitHub Token 새로 입력됨";
  }
  if (item.has_saved_token) {
    return "공간 전용 GitHub Token 저장됨";
  }
  return "공간 전용 GitHub Token 입력 필요";
}

function repoMappingTokenActionButton(item, index) {
  if (!(item.has_saved_token || item.github_token || item.clear_saved_token)) {
    return "";
  }
  return `
    <button
      type="button"
      class="ghost-button repo-mapping-item__token-toggle"
      data-repo-mapping-toggle-token="${index}"
    >
      ${escapeHtml(item.clear_saved_token ? "토큰 유지" : "공간 토큰 해제")}
    </button>
  `;
}

function currentRepoMappings() {
  return repoMappingState.items.map((item) => ({ ...item }));
}

function syncRepoMappingsField() {
  $("#repo_mappings").val(serializeRepoMappings(currentRepoMappings()));
}

function renderRepoMappings(items) {
  const rows = (items || [])
    .map((item, index) => `
      <div
        class="repo-mapping-item"
        data-space-key="${escapeHtml(item.space_key)}"
        data-repo-owner="${escapeHtml(item.repo_owner)}"
        data-repo-name="${escapeHtml(item.repo_name)}"
        data-base-branch="${escapeHtml(item.base_branch)}"
        data-local-repo-path="${escapeHtml(item.local_repo_path)}"
      >
        <div class="repo-mapping-item__summary">
          <strong>${escapeHtml(`공간명 ${item.space_key}`)}</strong>
          <span>${escapeHtml(`레포 ${item.repo_owner}/${item.repo_name}`)}</span>
          <span>${escapeHtml(`기준 브랜치 ${item.base_branch}`)}</span>
          <span>${escapeHtml(`로컬 경로 ${item.local_repo_path}`)}</span>
        </div>
        <button type="button" class="ghost-button repo-mapping-item__remove" data-repo-mapping-remove="${index}">삭제</button>
      </div>
    `)
    .join("");

  $("#repo_mapping_list").html(rows || '<p class="repo-mapping-empty">아직 추가된 공간 연결이 없습니다.</p>');
  syncRepoMappingsField();
  updateConfigFlowState();
}

function clearRepoMappingInputs() {
  $("#mapping_space_key").val("");
  $("#mapping_repo_owner").val("");
  $("#mapping_repo_name").val("");
  $("#mapping_base_branch").val("");
  $("#mapping_local_repo_path").val("");
}

function readRepoMappingInputs() {
  return {
    space_key: $("#mapping_space_key").val().trim().toUpperCase(),
    repo_owner: $("#mapping_repo_owner").val().trim(),
    repo_name: $("#mapping_repo_name").val().trim(),
    base_branch: $("#mapping_base_branch").val().trim(),
    local_repo_path: $("#mapping_local_repo_path").val().trim(),
  };
}

function collectConfig() {
  syncRepoMappingsField();
  return {
    jira_base_url: $("#jira_base_url").val().trim(),
    jira_email: $("#jira_email").val().trim(),
    jira_api_token: $("#jira_api_token").val().trim(),
    jira_jql: $("#jira_jql").val().trim(),
    github_owner: $("#github_owner").val().trim(),
    github_repo: $("#github_repo").val().trim(),
    github_base_branch: $("#github_base_branch").val().trim(),
    github_token: $("#github_token").val().trim(),
    repo_mappings: $("#repo_mappings").val().trim(),
    local_repo_path: $("#local_repo_path").val().trim(),
  };
}

function collectWorkflow() {
  const issue = selectedIssue();
  const detail = issue && jiraState.selectedIssueDetail && jiraState.selectedIssueDetail.issue_key === issue.issue_key
    ? jiraState.selectedIssueDetail
    : null;
  return {
    issue_key: $("#issue_key").val().trim(),
    issue_summary: $("#issue_summary").val().trim(),
    branch_name: $("#branch_name").val().trim(),
    commit_message: $("#commit_message").val().trim(),
    codex_model: $("#codex_model").val().trim(),
    codex_reasoning_effort: $("#codex_reasoning_effort").val().trim(),
    work_instruction: $("#work_instruction").val().trim(),
    acceptance_criteria: $("#acceptance_criteria").val().trim(),
    test_command: $("#test_command").val().trim(),
    commit_checklist: $("#commit_checklist").val().trim(),
    git_author_name: $("#git_author_name").val().trim(),
    git_author_email: $("#git_author_email").val().trim(),
    issue_status: detail ? (detail.status || "") : "",
    issue_type: detail ? (detail.issue_type || "") : "",
    issue_priority: detail ? (detail.priority || "") : "",
    issue_assignee: detail ? (detail.assignee || "") : "",
    issue_labels: detail ? ((detail.labels || []).join(", ")) : "",
    issue_description: detail ? (detail.description || "") : "",
    issue_comments_text: detail ? (detail.comments_text || "") : "",
    clarification_questions: workflowState.clarificationQuestions.map((item) => ({ ...item })),
    clarification_answers: { ...workflowState.clarificationAnswers },
    allow_auto_commit: $("#allow_auto_commit").is(":checked"),
    enable_plan_review: $("#enable_plan_review").is(":checked"),
  };
}

function workflowRequiredFields(payload) {
  return ["issue_key", "issue_summary", "branch_name", "commit_message", "work_instruction"]
    .filter((field) => !String(payload[field] || "").trim());
}

function requestedInfoForFields(fields) {
  const automationMap = {
    branch_name: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    commit_message: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    codex_model: { guide_section: "automation", guide_step_id: "automation-codex-model" },
    codex_reasoning_effort: { guide_section: "automation", guide_step_id: "automation-codex-model" },
    work_instruction: { guide_section: "automation", guide_step_id: "automation-work-instruction" },
    acceptance_criteria: { guide_section: "automation", guide_step_id: "automation-acceptance-criteria" },
    commit_checklist: { guide_section: "automation", guide_step_id: "automation-commit-checklist" },
    git_author_name: { guide_section: "automation", guide_step_id: "automation-git-author" },
    git_author_email: { guide_section: "automation", guide_step_id: "automation-git-author" },
    issue_key: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    issue_summary: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
  };

  return fields.map((field) => ({
    field,
    label: fieldLabel(field),
    guide_section: automationMap[field] ? automationMap[field].guide_section : "automation",
    guide_step_id: automationMap[field] ? automationMap[field].guide_step_id : "",
  }));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setResult(id, payload) {
  const targetId = String(id || "").trim();
  if (targetId === "#config_result") {
    console.info("[config]", payload);
  }
  const target = $(targetId);
  if (!target.length) {
    return;
  }
  target.text(JSON.stringify(payload, null, 2));
  if (targetId === "#workflow_result") {
    $("#workflow_result_panel").prop("hidden", !payload);
  }
}

function clearResultActions(targetId) {
  $(targetId).empty();
}

function repoMappingTokenSummary(item) {
  if (item.clear_saved_token) {
    return "공간 전용 GitHub Token 제거 예정";
  }
  if (item.github_token) {
    return "공간 전용 GitHub Token 새로 입력됨";
  }
  if (item.has_saved_token) {
    return "공간 전용 GitHub Token 저장됨";
  }
  return "공간 전용 GitHub Token 입력 필요";
}

function repoMappingTokenActionButton(item, index) {
  if (!(item.has_saved_token || item.github_token || item.clear_saved_token)) {
    return "";
  }
  return `
    <button
      type="button"
      class="ghost-button repo-mapping-item__token-toggle"
      data-repo-mapping-toggle-token="${index}"
    >
      ${escapeHtml(item.clear_saved_token ? "토큰 유지" : "공간 토큰 해제")}
    </button>
  `;
}

function currentRepoMappings() {
  return repoMappingState.items.map((item) => ({ ...item }));
}

function syncRepoMappingsField() {
  $("#repo_mappings").val(serializeRepoMappings(currentRepoMappings()));
}

function renderRepoMappings(items) {
  repoMappingState.items = (items || []).map((item) => ({
    space_key: String(item.space_key || "").trim().toUpperCase(),
    repo_owner: String(item.repo_owner || "").trim(),
    repo_name: String(item.repo_name || "").trim(),
    base_branch: String(item.base_branch || "").trim(),
    local_repo_path: String(item.local_repo_path || "").trim(),
    github_token: String(item.github_token || "").trim(),
    has_saved_token: Boolean(item.has_saved_token),
    clear_saved_token: Boolean(item.clear_saved_token),
  }));

  const rows = repoMappingState.items
    .map((item, index) => `
      <div class="repo-mapping-item">
        <div class="repo-mapping-item__summary">
          <strong>${escapeHtml(`공간명 ${item.space_key}`)}</strong>
          <span>${escapeHtml(`저장소 ${item.repo_owner}/${item.repo_name}`)}</span>
          <span>${escapeHtml(`기본 브랜치 ${item.base_branch}`)}</span>
          <span>${escapeHtml(`로컬 경로 ${item.local_repo_path}`)}</span>
          <span class="repo-mapping-token-status">${escapeHtml(repoMappingTokenSummary(item))}</span>
        </div>
        <div class="repo-mapping-item__actions">
          <button type="button" class="ghost-button repo-mapping-item__edit" data-repo-mapping-edit="${index}">편집</button>
          <button type="button" class="ghost-button repo-mapping-item__remove" data-repo-mapping-remove="${index}">제거</button>
        </div>
      </div>
    `)
    .join("");

  $("#repo_mapping_list").html(rows || '<p class="repo-mapping-empty">아직 추가한 공간 연결이 없습니다.</p>');
  syncRepoMappingsField();
  updateConfigFlowState();
}

function clearRepoMappingInputs() {
  $("#mapping_space_key").val("");
  $("#mapping_repo_owner").val("");
  $("#mapping_repo_name").val("");
  $("#mapping_base_branch").val("");
  $("#mapping_local_repo_path").val("");
  $("#mapping_github_token").val("");
}

function readRepoMappingInputs() {
  return {
    space_key: $("#mapping_space_key").val().trim().toUpperCase(),
    repo_owner: $("#mapping_repo_owner").val().trim(),
    repo_name: $("#mapping_repo_name").val().trim(),
    base_branch: $("#mapping_base_branch").val().trim(),
    local_repo_path: $("#mapping_local_repo_path").val().trim(),
    github_token: $("#mapping_github_token").val().trim(),
    has_saved_token: false,
    clear_saved_token: false,
  };
}

function syncRepoMappingEditDraftFromForm() {
  if (!repoMappingState.editingDraft) {
    return null;
  }

  const nextToken = $("#repo_mapping_edit_github_token").val().trim();
  repoMappingState.editingDraft = {
    ...repoMappingState.editingDraft,
    space_key: $("#repo_mapping_edit_space_key").val().trim().toUpperCase(),
    repo_owner: $("#repo_mapping_edit_repo_owner").val().trim(),
    repo_name: $("#repo_mapping_edit_repo_name").val().trim(),
    base_branch: $("#repo_mapping_edit_base_branch").val().trim(),
    local_repo_path: $("#repo_mapping_edit_local_repo_path").val().trim(),
    github_token: nextToken,
    clear_saved_token: nextToken ? false : Boolean(repoMappingState.editingDraft.clear_saved_token),
  };

  return repoMappingState.editingDraft;
}

function updateRepoMappingModalTokenControls() {
  const draft = repoMappingState.editingDraft;
  const button = $("#repo_mapping_edit_toggle_token");
  const status = $("#repo_mapping_edit_token_status");
  if (draft && draft.has_saved_token && !draft.clear_saved_token && !draft.github_token) {
    button.prop("disabled", false).text("저장된 토큰 해제");
    status.text("현재 저장된 토큰이 있습니다.");
    return;
  }

  if (!draft) {
    button.prop("disabled", true).text("저장된 토큰 없음");
    status.text("저장된 토큰 상태를 표시한다.");
    return;
  }

  if (draft.clear_saved_token) {
    button.prop("disabled", false).text("해제 취소");
    status.text("저장된 공간 토큰을 해제할 예정이다. 새 토큰을 입력하면 해제 대신 교체한다.");
    return;
  }

  if (draft.github_token) {
    button.prop("disabled", false).text("입력 토큰 비우기");
    status.text(draft.has_saved_token
      ? "새 토큰이 입력되었다. 저장하면 기존 공간 토큰을 새 값으로 교체한다."
      : "새 토큰이 입력되었다. 저장하면 이 공간 전용 토큰으로 저장한다.");
    return;
  }

  if (draft.has_saved_token) {
    button.prop("disabled", false).text("저장된 토큰 해제");
    status.text("저장된 공간 토큰이 있다. 비워두면 유지하고, 버튼을 누르면 해제 예정으로 바뀐다.");
    return;
  }

  button.prop("disabled", true).text("저장된 토큰 없음");
  status.text("저장된 공간 토큰이 없다. 필요하면 새 토큰을 입력한다.");
}

function clearRepoMappingModal() {
  repoMappingState.editingIndex = null;
  repoMappingState.editingDraft = null;
  $("#repo_mapping_edit_form").trigger("reset");
  updateRepoMappingModalTokenControls();
}

function closeRepoMappingModal() {
  clearRepoMappingModal();
  $("#repo_mapping_modal").removeClass("is-open").attr("aria-hidden", "true");
  syncModalBodyState();
}

function openRepoMappingModal(index) {
  const items = currentRepoMappings();
  const target = items[index];
  if (!target) {
    return;
  }

  repoMappingState.editingIndex = index;
  repoMappingState.editingDraft = { ...target };
  $("#repo_mapping_edit_space_key").val(target.space_key);
  $("#repo_mapping_edit_repo_owner").val(target.repo_owner);
  $("#repo_mapping_edit_repo_name").val(target.repo_name);
  $("#repo_mapping_edit_base_branch").val(target.base_branch);
  $("#repo_mapping_edit_local_repo_path").val(target.local_repo_path);
  $("#repo_mapping_edit_github_token").val(target.github_token || "");
  updateRepoMappingModalTokenControls();
  $("#repo_mapping_modal").addClass("is-open").attr("aria-hidden", "false");
  syncModalBodyState();
  window.setTimeout(() => $("#repo_mapping_edit_space_key").trigger("focus"), 0);
}

function saveRepoMappingModal() {
  const editIndex = Number(repoMappingState.editingIndex);
  const draft = syncRepoMappingEditDraftFromForm();
  if (!Number.isInteger(editIndex) || editIndex < 0 || !draft) {
    return;
  }

  const missing = ["space_key", "repo_owner", "repo_name", "base_branch", "local_repo_path"]
    .filter((key) => !String(draft[key] || "").trim());
  if (missing.length) {
    setResult("#config_result", {
      ok: false,
      error: "repo_mapping_fields_missing",
      fields: missing,
      message: "공간명, owner, repo, base branch, local path를 모두 입력해 주세요.",
    });
    const firstInputSelector = {
      space_key: "#repo_mapping_edit_space_key",
      repo_owner: "#repo_mapping_edit_repo_owner",
      repo_name: "#repo_mapping_edit_repo_name",
      base_branch: "#repo_mapping_edit_base_branch",
      local_repo_path: "#repo_mapping_edit_local_repo_path",
    }[missing[0]];
    if (firstInputSelector) {
      $(firstInputSelector).trigger("focus");
    }
    return;
  }

  const duplicateIndex = currentRepoMappings().findIndex((item, index) => index !== editIndex && item.space_key === draft.space_key);
  if (duplicateIndex >= 0) {
    setResult("#config_result", {
      ok: false,
      error: "repo_mapping_space_key_duplicate",
      field: "space_key",
      message: `이미 등록된 공간 키다: ${draft.space_key}`,
    });
    $("#repo_mapping_edit_space_key").trigger("focus");
    return;
  }

  const items = currentRepoMappings();
  items[editIndex] = { ...draft };
  closeRepoMappingModal();
  renderRepoMappings(items);
  setResult("#config_result", { ok: true, message: `매핑을 수정했습니다: ${draft.space_key}` });
}

function setGithubTokenHelp(saved) {
  const helpText = saved
    ? "저장된 공간 전용 토큰이 있다. 새 값을 비워도 기존 공간 토큰은 유지된다."
    : "각 공간 연결에는 GitHub Token이 필요하다. 선택한 이슈의 공간 키와 정확히 일치하는 연결만 사용한다.";
  $("#github_token_help").text(helpText);
}

function fillConfig(data) {
  const savedTokenSpaces = new Set((data.repo_mapping_token_spaces || []).map((item) => String(item || "").trim().toUpperCase()));
  const repoMappings = parseRepoMappingsText(data.repo_mappings || "").map((item) => ({
    ...item,
    has_saved_token: savedTokenSpaces.has(item.space_key),
  }));
  renderRepoMappings(repoMappings);
  Object.keys(data).forEach((key) => {
    if (["repo_mappings", "repo_mapping_token_spaces", "github_token_saved", "jira_api_token_saved"].includes(key)) {
      return;
    }
    const el = $("#" + key);
    if (el.length) {
      el.val(data[key]);
    }
  });
  setSavedSecretState("#jira_api_token", Boolean(data.jira_api_token_saved), "현재 저장된 토큰이 있습니다.", "Jira API Token");
  setGithubTokenHelp(savedTokenSpaces.size > 0);
  updateConfigFlowState();
}

function collectConfig() {
  syncRepoMappingsField();
  const repoMappingTokens = {};
  const repoMappingTokenClears = [];
  currentRepoMappings().forEach((item) => {
    if (item.github_token) {
      repoMappingTokens[item.space_key] = item.github_token;
      return;
    }
    if (item.clear_saved_token) {
      repoMappingTokenClears.push(item.space_key);
    }
  });

  return {
    jira_base_url: $("#jira_base_url").val().trim(),
    jira_email: $("#jira_email").val().trim(),
    jira_api_token: $("#jira_api_token").val().trim(),
    jira_jql: $("#jira_jql").val().trim(),
    github_owner: $("#github_owner").val().trim(),
    github_repo: $("#github_repo").val().trim(),
    github_base_branch: $("#github_base_branch").val().trim(),
    github_token: $("#github_token").val().trim(),
    repo_mappings: $("#repo_mappings").val().trim(),
    repo_mapping_tokens: repoMappingTokens,
    repo_mapping_token_clears: repoMappingTokenClears,
    local_repo_path: $("#local_repo_path").val().trim(),
  };
}

function setGithubTokenHelp(saved) {
  const helpText = saved
    ? "저장된 공간 전용 토큰이 있다. 새 값을 비워도 기존 공간 토큰은 유지된다."
    : "각 공간 연결에는 GitHub Token이 필요하다. 선택한 이슈의 공간 키와 정확히 일치하는 연결만 사용한다.";
  $("#github_token_help").text(helpText);
}

function collectConfig() {
  syncRepoMappingsField();
  const repoMappingTokens = {};
  const repoMappingTokenClears = [];
  currentRepoMappings().forEach((item) => {
    if (item.github_token) {
      repoMappingTokens[item.space_key] = item.github_token;
      return;
    }
    if (item.clear_saved_token) {
      repoMappingTokenClears.push(item.space_key);
    }
  });

  return {
    jira_base_url: readTextValue("#jira_base_url"),
    jira_email: readTextValue("#jira_email"),
    jira_api_token: readTextValue("#jira_api_token"),
    jira_jql: readTextValue("#jira_jql"),
    repo_mappings: readTextValue("#repo_mappings"),
    repo_mapping_tokens: repoMappingTokens,
    repo_mapping_token_clears: repoMappingTokenClears,
  };
}

function fillWorkflow(data) {
  clearWorkflowClarification();
  Object.keys(data).forEach((key) => {
    const el = $("#" + key);
    if (el.length) {
      const currentValue = String(el.val() || "").trim();
      const nextValue = data[key];
      if (nextValue == null) {
        return;
      }
      if ((key === "codex_model" || key === "codex_reasoning_effort") && currentValue) {
        return;
      }
      el.val(nextValue);
    }
  });
}

function selectedIssue() {
  const checked = $("input[name='selected_issue']:checked");
  if (checked.length) {
    return {
      issue_key: checked.data("key"),
      issue_summary: checked.data("summary"),
    };
  }

  const issueKey = $("#issue_key").val().trim();
  const issueSummary = $("#issue_summary").val().trim();
  if (!issueKey || !issueSummary) {
    return null;
  }
  return { issue_key: issueKey, issue_summary: issueSummary };
}

function normalizeWorkspaceView(view) {
  return String(view || "").trim() === "operations" ? "operations" : "prepare";
}

function workspaceViewElement(view) {
  return normalizeWorkspaceView(view) === "operations"
    ? $("#workspace_operations_view")
    : $("#workspace_prepare_view");
}

function activeWorkspaceViewElement() {
  return workspaceViewElement(workspaceState.view);
}

function workspaceIsMobileLayout() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function setWorkspaceViewInteractivity(view, isActive) {
  view.attr("aria-hidden", String(!isActive));
  if (view.length && view[0]) {
    view[0].inert = !isActive;
  }
}

function clearWorkspaceViewInlineStyle(view) {
  view.css({
    position: "",
    top: "",
    left: "",
    width: "",
    transform: "",
    opacity: "",
    visibility: "",
    pointerEvents: "",
  });
}

function syncWorkspaceViewButtons(view) {
  const normalized = normalizeWorkspaceView(view);
  $("#show_operations_view").prop("hidden", normalized !== "prepare");
  $("#show_prepare_view").prop("hidden", normalized !== "operations");
}

function finalizeWorkspaceViewState(view) {
  const normalized = normalizeWorkspaceView(view);
  const shell = $("#workspace_shell");
  const prepareView = $("#workspace_prepare_view");
  const operationsView = $("#workspace_operations_view");
  const activeView = workspaceViewElement(normalized);
  const inactiveView = normalized === "operations" ? prepareView : operationsView;

  workspaceState.view = normalized;
  workspaceState.isTransitioning = false;

  shell
    .toggleClass("workspace-shell--prepare", normalized === "prepare")
    .toggleClass("workspace-shell--operations", normalized === "operations");

  activeView.addClass("is-active").removeClass("is-transitioning");
  inactiveView.removeClass("is-active is-transitioning");
  clearWorkspaceViewInlineStyle(activeView);
  clearWorkspaceViewInlineStyle(inactiveView);
  setWorkspaceViewInteractivity(activeView, true);
  setWorkspaceViewInteractivity(inactiveView, false);
  syncWorkspaceViewButtons(normalized);
}

function requestWorkspaceShellHeightSync(animated = false) {
  if (workspaceState.shellHeightRaf) {
    window.cancelAnimationFrame(workspaceState.shellHeightRaf);
  }
  workspaceState.shellHeightRaf = window.requestAnimationFrame(() => {
    workspaceState.shellHeightRaf = 0;
    syncWorkspaceShellHeight(animated);
  });
}

function syncWorkspaceShellHeight(animated = false) {
  return;
}

function bindWorkspaceShellHeightObserver() {
  return;
}

function setWorkspaceView(view) {
  const normalized = normalizeWorkspaceView(view);
  const shell = $("#workspace_shell");
  const prepareView = $("#workspace_prepare_view");
  const operationsView = $("#workspace_operations_view");

  if (!shell.length || !prepareView.length || !operationsView.length) {
    return;
  }

  if (workspaceState.view === normalized || workspaceIsMobileLayout()) {
    finalizeWorkspaceViewState(normalized);
    if (normalized === "prepare") {
      window.requestAnimationFrame(() => {
        refreshBacklogLayout();
      });
    }
    return;
  }
  finalizeWorkspaceViewState(normalized);
  if (normalized === "prepare") {
    window.requestAnimationFrame(() => {
      refreshBacklogLayout();
    });
  }
}

function currentCheckedIssueKeys() {
  return $("input[name='selected_issue']:checked, input[name='selected_issues']:checked")
    .map(function () {
      return String($(this).data("key") || "").trim();
    })
    .get()
    .filter(Boolean);
}

function preferredBacklogIssueKey() {
  const checkedKeys = currentCheckedIssueKeys();
  if (checkedKeys.length) {
    return checkedKeys[0];
  }
  const expandedKey = String(jiraState.expandedIssueKey || jiraState.pendingIssueKey || "").trim();
  if (expandedKey) {
    return expandedKey;
  }
  const hiddenKey = String($("#issue_key").val() || "").trim();
  return hiddenKey;
}

function backlogColumnCount() {
  const shellWidth = $("#jira_backlog_table_shell").innerWidth() || 0;
  if (shellWidth >= 1500) {
    return 3;
  }
  if (shellWidth >= 980) {
    return 2;
  }
  return 1;
}

function backlogItemsPerPage(columns) {
  return Math.max((Number(columns) || 1) * 2, 1);
}

function backlogPageCount() {
  if (!jiraState.backlogIssues.length) {
    return 0;
  }
  return Math.max(Math.ceil(jiraState.backlogIssues.length / jiraState.backlogItemsPerPage), 1);
}

function setBacklogPage(index) {
  const totalPages = backlogPageCount();
  const normalized = Math.min(Math.max(Number(index) || 0, 0), Math.max(totalPages - 1, 0));
  jiraState.backlogPageIndex = normalized;
  $("#issue_table").css("transform", `translateX(-${normalized * 100}%)`);
  renderBacklogPagination(totalPages, normalized);
  $("#jira_backlog_pagination [data-jira-backlog-page]").each(function () {
    const isActive = Number($(this).attr("data-jira-backlog-page")) === normalized;
    $(this)
      .toggleClass("is-active", isActive)
      .attr("aria-current", isActive ? "page" : "false");
  });
}

function renderBacklogPagination(totalPages) {
  const pagination = $("#jira_backlog_pagination");
  if (totalPages <= 1) {
    pagination.empty().prop("hidden", true);
    return;
  }
  const dots = Array.from({ length: totalPages }, (_, index) => `
    <button
      type="button"
      class="jira-backlog-pagination__dot"
      data-jira-backlog-page="${index}"
      aria-label="${index + 1}페이지 보기"
    >
      ${index + 1}
    </button>
  `).join("");
  pagination.html(dots).prop("hidden", false);
}

function renderBacklogPagination(totalPages, activePage) {
  const pagination = $("#jira_backlog_pagination");
  if (totalPages <= 1) {
    pagination.empty().prop("hidden", true);
    return;
  }
  const current = Math.min(Math.max(Number(activePage) || 0, 0), Math.max(totalPages - 1, 0));
  const windowSize = Math.min(5, totalPages);
  const half = Math.floor(windowSize / 2);
  let start = Math.max(current - half, 0);
  let end = start + windowSize;
  if (end > totalPages) {
    end = totalPages;
    start = Math.max(end - windowSize, 0);
  }
  const dots = Array.from({ length: end - start }, (_, offset) => start + offset)
    .map((index) => `
      <button
        type="button"
        class="jira-backlog-pagination__dot"
        data-jira-backlog-page="${index}"
        aria-label="${index + 1}페이지 보기"
      >
        ${index + 1}
      </button>
    `)
    .join("");
  pagination.html(dots).prop("hidden", false);
}

function renderBacklogIssueTable(issues, options) {
  const settings = options || {};
  const items = Array.isArray(issues) ? issues : [];
  const checkedKeys = new Set(currentCheckedIssueKeys());
  const columns = backlogColumnCount();
  const itemsPerPage = backlogItemsPerPage(columns);
  const preferredKey = preferredBacklogIssueKey();
  const preferredIndex = preferredKey
    ? items.findIndex((issue) => String(issue.issue_key || issue.key || "").trim() === preferredKey)
    : -1;
  const shouldPreservePage = Boolean(settings.preservePage);

  jiraState.backlogIssues = items.slice();
  jiraState.backlogInputType = settings.inputType || "radio";
  jiraState.backlogInputName = settings.inputName || "selected_issue";
  jiraState.backlogColumns = columns;
  jiraState.backlogItemsPerPage = itemsPerPage;

  if (shouldPreservePage) {
    jiraState.backlogPageIndex = Math.min(
      Math.max(Number(jiraState.backlogPageIndex) || 0, 0),
      Math.max(Math.ceil(Math.max(items.length, 1) / itemsPerPage) - 1, 0)
    );
  } else if (preferredIndex >= 0) {
    jiraState.backlogPageIndex = Math.floor(preferredIndex / itemsPerPage);
  } else {
    jiraState.backlogPageIndex = 0;
  }

  if (!items.length) {
    $("#issue_table")
      .removeClass("jira-backlog-list--pages")
      .html('<p class="batch-preview-empty">조회된 이슈가 없습니다.</p>')
      .css("transform", "");
    $("#jira_backlog_pagination").empty().prop("hidden", true);
    return;
  }

  const pages = [];
  for (let index = 0; index < items.length; index += itemsPerPage) {
    pages.push(items.slice(index, index + itemsPerPage));
  }

  const pageHtml = pages
    .map((pageItems) => `
      <section class="jira-backlog-page" style="--jira-backlog-columns: ${columns};">
        ${pageItems
          .map((issue) => renderIssueAccordionItem(issue, {
            checked: checkedKeys.has(String(issue.issue_key || issue.key || "").trim()),
            inputType: jiraState.backlogInputType,
            inputName: jiraState.backlogInputName,
          }))
          .join("")}
      </section>
    `)
    .join("");

  $("#issue_table")
    .addClass("jira-backlog-list--pages")
    .html(pageHtml)
    .css("transform", "");
  setBacklogPage(jiraState.backlogPageIndex);
}

function populateIssueBacklog(data, options) {
  renderBacklogIssueTable((data && data.issues) || [], options);
  syncIssueAccordionState();
  const issue = selectedIssue();
  if (issue) {
    fillWorkflow(issue);
    loadIssueDetail(issue.issue_key);
  } else {
    resetIssueDetail();
  }
  syncWorkspaceShellHeight(false);
}

window.renderBacklogIssueTable = renderBacklogIssueTable;
window.populateIssueBacklog = populateIssueBacklog;
window.syncWorkspaceShellHeight = syncWorkspaceShellHeight;
setupIssueTable = function setupIssueTablePatched(data) {
  populateIssueBacklog(data, {
    inputType: "radio",
    inputName: "selected_issue",
  });
};
window.setupIssueTable = setupIssueTable;

function ensureBacklogIssuePage(issueKey) {
  const key = String(issueKey || "").trim();
  if (!key || !jiraState.backlogIssues.length || !jiraState.backlogItemsPerPage) {
    return;
  }
  const issueIndex = jiraState.backlogIssues.findIndex((issue) => String(issue.issue_key || issue.key || "").trim() === key);
  if (issueIndex < 0) {
    return;
  }
  setBacklogPage(Math.floor(issueIndex / jiraState.backlogItemsPerPage));
}

function refreshBacklogLayout() {
  if (!jiraState.backlogIssues.length) {
    return;
  }
  renderBacklogIssueTable(jiraState.backlogIssues, {
    inputType: jiraState.backlogInputType,
    inputName: jiraState.backlogInputName,
    preservePage: true,
  });
  if (typeof syncIssueAccordionState === "function") {
    syncIssueAccordionState();
  }
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function getSetupGuide() {
  if (guideState.guide) {
    return $.Deferred().resolve(guideState.guide).promise();
  }
  if (guideState.guidePromise) {
    return guideState.guidePromise;
  }

  guideState.guidePromise = $.getJSON("/api/setup-guide")
    .done((data) => {
      guideState.guide = data;
    })
    .fail(() => {
      guideState.guidePromise = null;
    });

  return guideState.guidePromise;
}

function guideSections() {
  return (guideState.guide && guideState.guide.sections) || [];
}

function findSection(sectionId) {
  return guideSections().find((section) => section.id === sectionId) || null;
}

function findStep(section, stepId) {
  return (section.steps || []).find((step) => step.id === stepId) || null;
}

function normalizeGuideTarget(sectionId, stepId) {
  const sections = guideSections();
  const section = findSection(sectionId) || sections[0] || null;
  const step = section ? findStep(section, stepId) || section.steps[0] || null : null;
  return { section, step };
}

function fieldLabel(fieldId) {
  return FIELD_LABELS[fieldId] || fieldId;
}

function readTextValue(selector) {
  const element = $(selector);
  return String(element.val() || "").trim();
}

function hasSavedSecret(selector) {
  return $(selector).attr("data-has-saved-secret") === "true";
}

function setSavedSecretState(selector, hasSaved, savedPlaceholder, defaultPlaceholder) {
  const element = $(selector);
  if (!element.length) {
    return;
  }
  const normalizedDefault = defaultPlaceholder || "";
  const normalizedSaved = savedPlaceholder || normalizedDefault;
  const hasValue = Boolean(String(element.val() || "").trim());
  element.attr("data-has-saved-secret", hasSaved ? "true" : "false");
  element.attr("placeholder", hasSaved && !hasValue ? normalizedSaved : normalizedDefault);
}

function syncModalBodyState() {
  $("body").toggleClass("modal-open", $(".modal-shell.is-open").length > 0);
}

function openConfigPanel(panelKey) {
  const normalized = String(panelKey || "").trim();
  if (!normalized) {
    return;
  }
  $("[data-config-panel]").each(function () {
    const isTarget = String($(this).attr("data-config-panel") || "").trim() === normalized;
    $(this).prop("open", isTarget);
  });
}

function closeConfigPanel(panelKey) {
  const normalized = String(panelKey || "").trim();
  if (!normalized) {
    return;
  }
  $(`[data-config-panel="${normalized}"]`).prop("open", false);
}

function isJiraConfigComplete() {
  return ["#jira_base_url", "#jira_email", "#jira_jql"].every((selector) => readTextValue(selector))
    && (Boolean(readTextValue("#jira_api_token")) || hasSavedSecret("#jira_api_token"));
}

function updateConfigFlowState() {
  const jiraComplete = isJiraConfigComplete();
  const repoCount = currentRepoMappings().length;
  const repoComplete = repoCount > 0;

  $("#jira_config_status")
    .text(jiraComplete ? "입력 완료" : "4개 입력 필요")
    .toggleClass("is-complete", jiraComplete);
  $("#repo_mapping_status")
    .text(repoComplete ? `공간 ${repoCount}개 연결됨` : "공간 연결 필요")
    .toggleClass("is-complete", repoComplete);
  $('[data-config-panel="jira"]').toggleClass("is-complete", jiraComplete);
  $('[data-config-panel="repo"]').toggleClass("is-complete", repoComplete);
}

function targetFieldBadges(fields) {
  return (fields || [])
    .map((field) => `<span class="field-pill">${escapeHtml(fieldLabel(field))}</span>`)
    .join("");
}

function renderGuideTabs(activeSection) {
  const tabs = guideSections()
    .map((section) => {
      const isActive = activeSection && section.id === activeSection.id;
      return `
        <button
          type="button"
          class="guide-tab${isActive ? " is-active" : ""}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
          data-guide-tab="true"
          data-guide-section="${escapeHtml(section.id)}"
        >
          <span>${escapeHtml(section.title)}</span>
          <span class="guide-tab__count">${section.steps.length}</span>
        </button>
      `;
    })
    .join("");

  $("#guide_tabs").html(tabs);
}

function renderGuideSteps(section, activeStep) {
  const steps = (section.steps || [])
    .map((step, index) => {
      const isActive = activeStep && step.id === activeStep.id;
      const caption = (step.target_fields || []).map((field) => fieldLabel(field)).join(" · ");
      return `
        <button
          type="button"
          class="guide-step${isActive ? " is-active" : ""}"
          data-guide-step="true"
          data-guide-section="${escapeHtml(section.id)}"
          data-guide-step-id="${escapeHtml(step.id)}"
        >
          <span class="guide-step__index">${String(index + 1).padStart(2, "0")}</span>
          <span class="guide-step__text">
            <strong>${escapeHtml(step.title)}</strong>
            <small>${escapeHtml(caption)}</small>
          </span>
        </button>
      `;
    })
    .join("");

  $("#guide_steps").html(steps);
}

function renderGuideDetail(section, step) {
  const stepIndex = (section.steps || []).findIndex((item) => item.id === step.id) + 1;
  const progress = section.steps.length ? (stepIndex / section.steps.length) * 100 : 0;
  const externalLink = step.external_url
    ? `<a class="ghost-button guide-link" href="${escapeHtml(step.external_url)}" target="_blank" rel="noreferrer">공식 페이지 열기</a>`
    : "";
  const instructionItems = (step.instructions || [])
    .map((instruction) => `<li>${escapeHtml(instruction)}</li>`)
    .join("");

  $("#guide_modal_summary").text(section.summary);
  $("#guide_progress_label").text(`${stepIndex} / ${section.steps.length}`);
  $("#guide_progress_fill").css("width", `${progress}%`);

  $("#guide_detail").html(`
    <div class="guide-detail__frame">
      <div class="guide-detail__intro">
        <p class="guide-detail__eyebrow">${escapeHtml(section.title)}</p>
        <h3>${escapeHtml(step.title)}</h3>
        <p class="guide-detail__lead">${escapeHtml(step.purpose || "")}</p>
      </div>

      <div class="guide-detail__group">
        <span class="guide-detail__label">왜 필요한지</span>
        <p>${escapeHtml(step.purpose || "")}</p>
      </div>

      <div class="guide-detail__group">
        <span class="guide-detail__label">어디서 찾는지</span>
        <ol>${instructionItems}</ol>
      </div>

      <div class="guide-detail__group">
        <span class="guide-detail__label">예시 값</span>
        <code>${escapeHtml(step.sample_value || "-")}</code>
      </div>

      <div class="guide-detail__group">
        <span class="guide-detail__label">주의사항</span>
        <p>${escapeHtml(step.tip || "없음")}</p>
      </div>

      <div class="guide-detail__group">
        <span class="guide-detail__label">이 값이 들어갈 입력칸</span>
        <div class="field-pill-row">${targetFieldBadges(step.target_fields)}</div>
      </div>

      <div class="guide-detail__actions">
        <button
          type="button"
          class="primary-button js-highlight-fields"
          data-guide-section="${escapeHtml(section.id)}"
          data-guide-step-id="${escapeHtml(step.id)}"
        >
          해당 입력칸 강조
        </button>
        ${externalLink}
      </div>
    </div>
  `);
}

function renderGuide() {
  const target = normalizeGuideTarget(guideState.activeSectionId, guideState.activeStepId);
  if (!target.section || !target.step) {
    $("#guide_detail").html('<p class="guide-empty">가이드 데이터를 불러오지 못했습니다.</p>');
    return;
  }

  guideState.activeSectionId = target.section.id;
  guideState.activeStepId = target.step.id;

  renderGuideTabs(target.section);
  renderGuideSteps(target.section, target.step);
  renderGuideDetail(target.section, target.step);
}

function openGuide(sectionId, stepId) {
  $.when(getSetupGuide())
    .done(() => {
      guideState.activeSectionId = sectionId;
      guideState.activeStepId = stepId;
      renderGuide();
      $("#setup_guide_modal").addClass("is-open").attr("aria-hidden", "false");
      syncModalBodyState();
    })
    .fail((xhr) => {
      setResult("#config_result", {
        ok: false,
        error: "setup_guide_load_failed",
        details: xhr.responseText || "guide endpoint unavailable",
      });
    });
}

function closeGuide() {
  $("#setup_guide_modal").removeClass("is-open").attr("aria-hidden", "true");
  syncModalBodyState();
}

function focusFields(fieldIds) {
  const ids = fieldIds || [];
  if (!ids.length) {
    return;
  }
  const jiraFields = ["jira_base_url", "jira_email", "jira_api_token", "jira_jql"];
  const repoFields = [
    "repo_mappings",
    "mapping_space_key",
    "mapping_provider",
    "mapping_repo_owner",
    "mapping_repo_name",
    "gitlab_base_url",
    "mapping_repo_ref",
    "mapping_base_branch",
    "mapping_local_repo_path",
    "mapping_scm_token",
  ];
  if (ids.some((fieldId) => jiraFields.includes(fieldId))) {
    openConfigPanel("jira");
  }
  if (ids.some((fieldId) => repoFields.includes(fieldId))) {
    openConfigPanel("repo");
  }

  window.setTimeout(() => {
    let firstInput = null;
    ids.forEach((fieldId, index) => {
      const input = $("#" + fieldId);
      const wrapper = input.closest("label");
      if (!input.length || !wrapper.length) {
        return;
      }

      if (!firstInput) {
        firstInput = input;
      }

      window.setTimeout(() => {
        wrapper.addClass("field-highlight");
        window.setTimeout(() => {
          wrapper.removeClass("field-highlight");
        }, 1800);
      }, index * 80);
    });

    if (firstInput && firstInput.length) {
      firstInput.get(0).scrollIntoView({
        behavior: prefersReducedMotion() ? "auto" : "smooth",
        block: "center",
      });
      firstInput.trigger("focus");
    }
  }, prefersReducedMotion() ? 0 : 120);
}

function renderCallout(targetId, requestedInformation) {
  clearResultActions(targetId);
  if (!requestedInformation || !requestedInformation.length) {
    return;
  }

  const firstMissing = requestedInformation[0];
  const shortcuts = requestedInformation
    .map((item) => `
      <button
        type="button"
        class="pill-button js-open-guide"
        data-guide-section="${escapeHtml(item.guide_section || "")}"
        data-guide-step-id="${escapeHtml(item.guide_step_id || "")}"
      >
        ${escapeHtml(item.label || item.field)}
      </button>
    `)
    .join("");

  $(targetId).html(`
    <div class="result-callout">
      <div>
        <strong>가이드에서 필요한 입력 항목을 바로 확인할 수 있습니다.</strong>
        <p>첫 번째 항목부터 위치, 예시 값, 주의사항을 확인하고 입력하세요.</p>
      </div>
      <div class="result-callout__actions">
        <button
          type="button"
          class="secondary-button js-open-guide"
          data-guide-section="${escapeHtml(firstMissing.guide_section || "")}"
          data-guide-step-id="${escapeHtml(firstMissing.guide_step_id || "")}"
        >
          첫 항목 안내 열기
        </button>
        <div class="pill-row">${shortcuts}</div>
      </div>
    </div>
  `);
}

function clearWorkflowClarification() {
  workflowState.clarificationQuestions = [];
  workflowState.clarificationAnswers = {};
  $("#workflow_clarification_panel").prop("hidden", true);
  $("#workflow_clarification_summary").text("작업 전에 추가 확인이 필요하면 여기에 표시합니다.");
  $("#workflow_clarification_questions").empty();
  $("#workflow_clarification_sync").prop("hidden", true);
  $("#workflow_clarification_sync_list").empty();
}

function syncWorkflowClarificationAnswers() {
  const answers = {};
  $("[data-clarification-answer]").each(function () {
    const field = String($(this).attr("data-clarification-answer") || "").trim();
    const value = String($(this).val() || "").trim();
    if (field && value) {
      answers[field] = value;
    }
  });
  workflowState.clarificationAnswers = answers;
  return answers;
}

function renderWorkflowClarification(data) {
  const requestedInformation = (data && data.requested_information) || [];
  if (!requestedInformation.length) {
    clearWorkflowClarification();
    return;
  }

  workflowState.clarificationQuestions = requestedInformation;
  const questionItems = requestedInformation
    .map((item) => {
      const answer = workflowState.clarificationAnswers[item.field] || "";
      return `
        <label class="clarification-question">
          <span class="clarification-question__label">${escapeHtml(item.label || item.field)}</span>
          <strong class="clarification-question__prompt">${escapeHtml(item.question || "")}</strong>
          <small class="clarification-question__reason">${escapeHtml(item.why || "")}</small>
          <textarea
            rows="3"
            data-clarification-answer="${escapeHtml(item.field)}"
            placeholder="${escapeHtml(item.placeholder || "답변을 입력하세요.")}"
          >${escapeHtml(answer)}</textarea>
        </label>
      `;
    })
    .join("");

  $("#workflow_clarification_summary").text(data.analysis_summary || "작업 전에 추가 확인이 필요합니다.");
  $("#workflow_clarification_questions").html(questionItems);
  $("#workflow_clarification_panel").prop("hidden", false);
  renderWorkflowClarificationSync(data);
}

function issueMetaValues(source, options) {
  const settings = options || {};
  const issue = source || {};
  return [
    settings.includeKey ? (issue.issue_key || issue.key || "") : "",
    issue.status ? `상태 ${issue.status}` : "",
    issue.issue_type ? `유형 ${issue.issue_type}` : "",
    issue.priority ? `우선순위 ${issue.priority}` : "",
    issue.assignee ? `담당 ${issue.assignee}` : "",
    ...(Array.isArray(issue.labels) ? issue.labels.map((label) => `라벨 ${label}`) : []),
  ].filter(Boolean);
}

function renderIssueMetaPills(source, options) {
  return issueMetaValues(source, options)
    .map((value) => `<span class="field-pill">${escapeHtml(value)}</span>`)
    .join("");
}

function renderIssueStatusPill(source) {
  return renderIssueMetaPills({ status: source && source.status ? source.status : "" });
}

function renderIssueBodyMetaPills(source) {
  const detail = source || {};
  const values = [
    detail.issue_type ? `?좏삎 ${detail.issue_type}` : "",
    detail.priority ? `?곗꽑?쒖쐞 ${detail.priority}` : "",
    detail.assignee ? `?대떦 ${detail.assignee}` : "",
    ...(Array.isArray(detail.labels) ? detail.labels.map((label) => `?쇰꺼 ${label}`) : []),
  ].filter(Boolean);
  return values.map((value) => `<span class="field-pill">${escapeHtml(value)}</span>`).join("");
}

function resetIssueMetaInline(item) {
  const status = String(item.attr("data-issue-status") || "").trim();
  const html = renderIssueStatusPill({ status });
  item.find("[data-jira-issue-meta-inline]").html(html).prop("hidden", !html);
}

function renderIssueAccordionItem(issue, options) {
  const settings = options || {};
  const checked = settings.checked ? 'checked="checked"' : "";
  const inputName = settings.inputName || "selected_issue";
  const inputType = settings.inputType || "radio";
  const safeKey = escapeHtml(issue.issue_key || issue.key || "");
  const safeSummary = escapeHtml(issue.issue_summary || issue.summary || "");
  const safeStatus = escapeHtml(issue.status || "");
  const metaHtml = renderIssueStatusPill({ status: issue.status || "" });
  return `
    <article class="jira-backlog-item ${settings.checked ? "is-selected" : ""}" data-issue-key="${safeKey}" data-issue-status="${safeStatus}">
      <div class="jira-backlog-item__row">
        <div class="jira-backlog-item__trigger" data-jira-issue-modal-open="${safeKey}" data-issue-summary="${safeSummary}" role="button" tabindex="0" aria-pressed="${settings.checked ? "true" : "false"}">
          <div class="jira-backlog-item__heading">
            <div class="jira-backlog-item__title">
              <strong>${safeKey}</strong>
              <span>${safeSummary}</span>
            </div>
            <div class="jira-backlog-item__meta" data-jira-issue-meta-inline ${metaHtml ? "" : "hidden"}>${metaHtml}</div>
          </div>
        </div>
        <label class="jira-backlog-item__selector">
          <input
            type="${inputType}"
            name="${inputName}"
            ${checked}
            data-key="${safeKey}"
            data-summary="${safeSummary}"
            aria-label="선택"
          >
          <span aria-hidden="true"></span>
        </label>
      </div>
      <div class="jira-backlog-item__body" data-jira-accordion-body ${settings.checked ? "" : "hidden"}>
        <div class="jira-backlog-item__meta jira-backlog-item__meta-body" data-jira-issue-meta-body hidden></div>
        <div class="jira-backlog-item__detail-grid">
          <section class="jira-backlog-item__detail-card">
            <h3>선택 이슈 상세</h3>
            <pre class="result result-medium" data-jira-issue-description>이슈를 선택하면 상세 설명을 표시한다.</pre>
          </section>
          <section class="jira-backlog-item__detail-card">
            <h3>최근 코멘트</h3>
            <pre class="result result-medium" data-jira-issue-comments>이슈를 선택하면 최근 코멘트를 표시한다.</pre>
          </section>
        </div>
      </div>
    </article>
  `;
}

function issueAccordionItems() {
  return $("#issue_table .jira-backlog-item");
}

function issueAccordionItem(issueKey) {
  const key = String(issueKey || "").trim();
  return issueAccordionItems().filter(function () {
    return String($(this).attr("data-issue-key") || "").trim() === key;
  }).first();
}

function renderIssueModal(detail, options) {
  const settings = options || {};
  const issueKey = String(detail.issue_key || settings.issue_key || "").trim();
  const summary = String(detail.summary || detail.issue_summary || settings.issue_summary || "").trim() || "제목 없음";
  const title = issueKey ? `${issueKey} ${summary}` : summary;
  const metaHtml = renderIssueMetaPills(detail, { includeKey: false }) || '<span class="field-pill">상세 정보를 불러오는 중</span>';
  const description = settings.description || detail.description || "이슈 상세를 불러오는 중이다.";
  const comments = settings.comments || detail.comments_text || "최근 코멘트를 불러오는 중이다.";

  $("#jira_issue_modal_title").text(title || "이슈 상세");
  $("#jira_issue_modal_meta").html(metaHtml);
  $("#jira_issue_modal_description").text(description);
  $("#jira_issue_modal_comments").text(comments);
}

function openIssueModal(issueKey, issueSummary) {
  const key = String(issueKey || "").trim();
  if (!key) {
    return;
  }
  jiraState.issueModalKey = key;
  const detail = jiraState.selectedIssueDetail && String(jiraState.selectedIssueDetail.issue_key || "").trim() === key
    ? jiraState.selectedIssueDetail
    : { issue_key: key, summary: issueSummary || "" };
  renderIssueModal(detail, {
    issue_key: key,
    issue_summary: issueSummary || "",
  });
  $("#jira_issue_modal").addClass("is-open").attr("aria-hidden", "false");
  syncModalBodyState();
}

function closeIssueModal() {
  jiraState.issueModalKey = null;
  $("#jira_issue_modal").removeClass("is-open").attr("aria-hidden", "true");
  syncModalBodyState();
}

function syncIssueAccordionState() {
  const checkedInputs = $("input[name='selected_issue']:checked, input[name='selected_issues']:checked");
  const selectedInput = checkedInputs.first();
  const selectedKey = String(selectedInput.data("key") || "").trim();
  if (!selectedKey) {
    jiraState.expandedIssueKey = null;
    jiraState.issueAccordionCollapsed = false;
  } else if (jiraState.issueAccordionCollapsed) {
    const selectedKeys = checkedInputs.map(function () {
      return String($(this).data("key") || "").trim();
    }).get();
    if (!selectedKeys.includes(jiraState.expandedIssueKey)) {
      jiraState.expandedIssueKey = selectedKey;
      jiraState.issueAccordionCollapsed = false;
    }
  } else if (!jiraState.expandedIssueKey || jiraState.expandedIssueKey === "") {
    jiraState.expandedIssueKey = selectedKey;
  } else {
    const selectedKeys = checkedInputs.map(function () {
      return String($(this).data("key") || "").trim();
    }).get();
    if (!selectedKeys.includes(jiraState.expandedIssueKey)) {
      jiraState.expandedIssueKey = selectedKey;
    }
  }

  issueAccordionItems().each(function () {
    const item = $(this);
    const checked = item.find("input[name='selected_issue'], input[name='selected_issues']").is(":checked");
    item.toggleClass("is-selected", checked);
    item.find(".jira-backlog-item__selector").toggleClass("is-checked", checked);
    item.find("[data-jira-issue-modal-open]").attr("aria-pressed", checked ? "true" : "false");
  });
}

function setupIssueTable(data) {
  const rows = (data.issues || [])
    .map((issue) => renderIssueAccordionItem(issue))
    .join("");

  $("#issue_table").html(rows || '<p class="batch-preview-empty">조회된 이슈가 없습니다.</p>');
  syncIssueAccordionState();
  const issue = selectedIssue();
  if (issue) {
    fillWorkflow(issue);
    loadIssueDetail(issue.issue_key);
  } else {
    resetIssueDetail();
  }
}

function resetIssueDetail(message) {
  jiraState.selectedIssueDetail = null;
  jiraState.pendingIssueKey = null;
  jiraState.expandedIssueKey = null;
  jiraState.issueAccordionCollapsed = false;
  issueAccordionItems().each(function () {
    const item = $(this);
    resetIssueMetaInline(item);
    item.find("[data-jira-issue-meta-body]").empty().prop("hidden", true);
    item.find("[data-jira-issue-description]").text(message || "이슈를 선택하면 상세 설명을 표시한다.");
    item.find("[data-jira-issue-comments]").text(message || "이슈를 선택하면 최근 코멘트를 표시한다.");
  });
  syncIssueAccordionState();
}

function renderIssueDetail(detail) {
  const item = issueAccordionItem(detail.issue_key);
  if (!item.length) {
    return;
  }
  item.attr("data-issue-status", String(detail.status || "").trim());
  item.find("[data-jira-issue-meta-inline]").html(renderIssueStatusPill(detail)).prop("hidden", false);
  const bodyMetaHtml = renderIssueBodyMetaPills(detail);
  item.find("[data-jira-issue-meta-body]").html(bodyMetaHtml).prop("hidden", !bodyMetaHtml);
  item.find("[data-jira-issue-description]").text(detail.description || "Jira 설명이 비어 있습니다.");
  item.find("[data-jira-issue-comments]").text(detail.comments_text || "최근 코멘트가 없습니다.");
  jiraState.expandedIssueKey = String(detail.issue_key || "").trim();
  jiraState.issueAccordionCollapsed = false;
  syncIssueAccordionState();
}

function loadIssueDetail(issueKey, options) {
  const key = String(issueKey || "").trim();
  const settings = options || {};
  if (!key) {
    resetIssueDetail();
    return;
  }
  if (!settings.preserveBacklogPage) {
    ensureBacklogIssuePage(key);
  }

  if (jiraState.issueDetailRequest && typeof jiraState.issueDetailRequest.abort === "function") {
    jiraState.issueDetailRequest.abort();
  }

  jiraState.expandedIssueKey = key;
  jiraState.issueAccordionCollapsed = false;
  syncIssueAccordionState();
  jiraState.pendingIssueKey = key;
  const item = issueAccordionItem(key);
  resetIssueMetaInline(item);
  item.find("[data-jira-issue-meta-body]").empty().prop("hidden", true);
  item.find("[data-jira-issue-description]").text(`${key} 상세를 불러오는 중입니다...`);
  item.find("[data-jira-issue-comments]").text(`${key} 코멘트를 불러오는 중입니다...`);

  jiraState.issueDetailRequest = $.ajax({
    url: "/api/jira/issue-detail",
    method: "POST",
    contentType: "application/json",
    data: JSON.stringify({
      issue_key: key,
      mock_mode: $("#mock_mode").is(":checked"),
    }),
  })
    .done((data) => {
      if (jiraState.pendingIssueKey !== key) {
        return;
      }
      jiraState.selectedIssueDetail = data;
      fillWorkflow({
        issue_key: data.issue_key,
        issue_summary: data.summary,
      });
      renderIssueDetail(data);
    })
    .fail((xhr) => {
      if (xhr.statusText === "abort") {
        return;
      }
      jiraState.selectedIssueDetail = null;
      const targetItem = issueAccordionItem(key);
      resetIssueMetaInline(targetItem);
      targetItem.find("[data-jira-issue-meta-body]").empty().prop("hidden", true);
      targetItem.find("[data-jira-issue-description]").text("이슈 상세를 불러오지 못했습니다.");
      targetItem.find("[data-jira-issue-comments]").text((xhr.responseJSON && xhr.responseJSON.error) || xhr.responseText || "오류");
    })
    .always(() => {
      if (jiraState.pendingIssueKey === key) {
        jiraState.pendingIssueKey = null;
      }
      jiraState.issueDetailRequest = null;
    });
}

function renderIssueBodyMetaPills(source) {
  const detail = source || {};
  const values = [
    detail.issue_type ? `유형 ${detail.issue_type}` : "",
    detail.priority ? `우선순위 ${detail.priority}` : "",
    detail.assignee ? `담당 ${detail.assignee}` : "",
    ...(Array.isArray(detail.labels) ? detail.labels.map((label) => `라벨 ${label}`) : []),
  ].filter(Boolean);
  return values.map((value) => `<span class="field-pill">${escapeHtml(value)}</span>`).join("");
}

function renderIssueAccordionItem(issue, options) {
  const settings = options || {};
  const checked = settings.checked ? 'checked="checked"' : "";
  const inputName = settings.inputName || "selected_issue";
  const inputType = settings.inputType || "radio";
  const safeKey = escapeHtml(issue.issue_key || issue.key || "");
  const safeSummary = escapeHtml(issue.issue_summary || issue.summary || "");
  const safeStatus = escapeHtml(issue.status || "");
  const metaHtml = renderIssueStatusPill({ status: issue.status || "" });
  return `
    <article class="jira-backlog-item ${settings.checked ? "is-selected" : ""}" data-issue-key="${safeKey}" data-issue-status="${safeStatus}">
      <div class="jira-backlog-item__row">
        <div class="jira-backlog-item__trigger" data-jira-accordion-trigger="${safeKey}" aria-expanded="${settings.checked ? "true" : "false"}">
          <div class="jira-backlog-item__heading">
            <div class="jira-backlog-item__title">
              <strong>${safeKey}</strong>
              <span>${safeSummary}</span>
            </div>
            <div class="jira-backlog-item__meta" data-jira-issue-meta-inline ${metaHtml ? "" : "hidden"}>${metaHtml}</div>
          </div>
        </div>
        <label class="jira-backlog-item__selector" aria-label="선택">
          <input
            type="${inputType}"
            name="${inputName}"
            ${checked}
            data-key="${safeKey}"
            data-summary="${safeSummary}"
            aria-label="선택"
          >
        </label>
      </div>
      <div class="jira-backlog-item__body" data-jira-accordion-body ${settings.checked ? "" : "hidden"}>
        <div class="jira-backlog-item__meta jira-backlog-item__meta-body" data-jira-issue-meta-body hidden></div>
        <div class="jira-backlog-item__detail-grid">
          <section class="jira-backlog-item__detail-card">
            <h3>선택 이슈 상세</h3>
            <pre class="result result-medium" data-jira-issue-description>이슈를 선택하면 상세 설명을 표시한다.</pre>
          </section>
          <section class="jira-backlog-item__detail-card">
            <h3>최근 코멘트</h3>
            <pre class="result result-medium" data-jira-issue-comments>이슈를 선택하면 최근 코멘트를 표시한다.</pre>
          </section>
        </div>
      </div>
    </article>
  `;
}

function resetIssueDetail(message) {
  jiraState.selectedIssueDetail = null;
  jiraState.pendingIssueKey = null;
  jiraState.expandedIssueKey = null;
  jiraState.issueAccordionCollapsed = false;
  issueAccordionItems().each(function () {
    const item = $(this);
    resetIssueMetaInline(item);
    item.find("[data-jira-issue-meta-body]").empty().prop("hidden", true);
    item.find("[data-jira-issue-description]").text(message || "이슈를 선택하면 상세 설명을 표시한다.");
    item.find("[data-jira-issue-comments]").text(message || "이슈를 선택하면 최근 코멘트를 표시한다.");
  });
  syncIssueAccordionState();
}

function renderIssueDetail(detail) {
  const item = issueAccordionItem(detail.issue_key);
  if (!item.length) {
    return;
  }
  item.attr("data-issue-status", String(detail.status || "").trim());
  item.find("[data-jira-issue-meta-inline]").html(renderIssueStatusPill(detail)).prop("hidden", false);
  const bodyMetaHtml = renderIssueBodyMetaPills(detail);
  item.find("[data-jira-issue-meta-body]").html(bodyMetaHtml).prop("hidden", !bodyMetaHtml);
  item.find("[data-jira-issue-description]").text(detail.description || "Jira 설명이 비어 있습니다.");
  item.find("[data-jira-issue-comments]").text(detail.comments_text || "최근 코멘트가 없습니다.");
  jiraState.expandedIssueKey = String(detail.issue_key || "").trim();
  jiraState.issueAccordionCollapsed = false;
  syncIssueAccordionState();
}

function renderIssueModal(detail, options) {
  const settings = options || {};
  const issueKey = String(detail.issue_key || settings.issue_key || "").trim();
  const summary = String(detail.summary || detail.issue_summary || settings.issue_summary || "").trim() || "제목 없음";
  const title = issueKey ? `${issueKey} ${summary}` : summary;
  const metaHtml = renderIssueMetaPills(detail, { includeKey: false }) || '<span class="field-pill">상세 정보를 불러오는 중</span>';
  const description = settings.description || detail.description || "이슈 상세를 불러오는 중이다.";
  const comments = settings.comments || detail.comments_text || "최근 코멘트를 불러오는 중이다.";

  $("#jira_issue_modal_title").text(title || "이슈 상세");
  $("#jira_issue_modal_meta").html(metaHtml);
  $("#jira_issue_modal_description").text(description);
  $("#jira_issue_modal_comments").text(comments);
}

function openIssueModal(issueKey, issueSummary) {
  const key = String(issueKey || "").trim();
  if (!key) {
    return;
  }
  jiraState.issueModalKey = key;
  const detail = jiraState.selectedIssueDetail && String(jiraState.selectedIssueDetail.issue_key || "").trim() === key
    ? jiraState.selectedIssueDetail
    : { issue_key: key, summary: issueSummary || "" };
  renderIssueModal(detail, {
    issue_key: key,
    issue_summary: issueSummary || "",
  });
  $("#jira_issue_modal").addClass("is-open").attr("aria-hidden", "false");
  syncModalBodyState();
}

function closeIssueModal() {
  jiraState.issueModalKey = null;
  $("#jira_issue_modal").removeClass("is-open").attr("aria-hidden", "true");
  syncModalBodyState();
}

function renderIssueAccordionItem(issue, options) {
  const settings = options || {};
  const checked = settings.checked ? 'checked="checked"' : "";
  const inputName = settings.inputName || "selected_issue";
  const inputType = settings.inputType || "radio";
  const safeKey = escapeHtml(issue.issue_key || issue.key || "");
  const safeSummary = escapeHtml(issue.issue_summary || issue.summary || "");
  const safeStatus = escapeHtml(issue.status || "");
  const metaHtml = renderIssueStatusPill({ status: issue.status || "" });
  return `
    <article class="jira-backlog-item ${settings.checked ? "is-selected" : ""}" data-issue-key="${safeKey}" data-issue-status="${safeStatus}">
      <div class="jira-backlog-item__row">
        <div class="jira-backlog-item__trigger" data-jira-issue-modal-open="${safeKey}" data-issue-summary="${safeSummary}" role="button" tabindex="0" aria-pressed="${settings.checked ? "true" : "false"}">
          <div class="jira-backlog-item__heading">
            <div class="jira-backlog-item__title">
              <strong>${safeKey}</strong>
              <span>${safeSummary}</span>
            </div>
            <div class="jira-backlog-item__meta" data-jira-issue-meta-inline ${metaHtml ? "" : "hidden"}>${metaHtml}</div>
          </div>
        </div>
        <label class="jira-backlog-item__selector" aria-label="선택">
          <input
            type="${inputType}"
            name="${inputName}"
            ${checked}
            data-key="${safeKey}"
            data-summary="${safeSummary}"
            aria-label="선택"
          >
        </label>
      </div>
    </article>
  `;
}

function syncIssueAccordionState() {
  const checkedInputs = $("input[name='selected_issue']:checked, input[name='selected_issues']:checked");
  const selectedInput = checkedInputs.first();
  const selectedKey = String(selectedInput.data("key") || "").trim();
  if (!selectedKey) {
    jiraState.expandedIssueKey = null;
    jiraState.issueAccordionCollapsed = false;
  } else {
    jiraState.expandedIssueKey = selectedKey;
    jiraState.issueAccordionCollapsed = false;
  }

  issueAccordionItems().each(function () {
    const item = $(this);
    const checked = item.find("input[name='selected_issue'], input[name='selected_issues']").is(":checked");
    item.toggleClass("is-selected", checked);
    item.find(".jira-backlog-item__selector").toggleClass("is-checked", checked);
    item.find("[data-jira-issue-modal-open]").attr("aria-pressed", checked ? "true" : "false");
  });
}

function resetIssueDetail(message) {
  jiraState.selectedIssueDetail = null;
  jiraState.pendingIssueKey = null;
  jiraState.expandedIssueKey = null;
  jiraState.issueAccordionCollapsed = false;
  issueAccordionItems().each(function () {
    resetIssueMetaInline($(this));
  });
  if (jiraState.issueModalKey) {
    renderIssueModal({ issue_key: jiraState.issueModalKey }, {
      description: message || "이슈를 선택하면 상세 설명을 표시한다.",
      comments: message || "이슈를 선택하면 최근 코멘트를 표시한다.",
    });
  }
  syncIssueAccordionState();
}

function renderIssueDetail(detail) {
  const item = issueAccordionItem(detail.issue_key);
  if (!item.length) {
    return;
  }
  item.attr("data-issue-status", String(detail.status || "").trim());
  item.find("[data-jira-issue-meta-inline]").html(renderIssueStatusPill(detail)).prop("hidden", false);
  jiraState.expandedIssueKey = String(detail.issue_key || "").trim();
  jiraState.issueAccordionCollapsed = false;
  if (jiraState.issueModalKey && jiraState.issueModalKey === jiraState.expandedIssueKey) {
    renderIssueModal(detail);
  }
  syncIssueAccordionState();
}

function loadIssueDetail(issueKey, options) {
  const key = String(issueKey || "").trim();
  const settings = options || {};
  if (!key) {
    resetIssueDetail();
    return;
  }
  if (!settings.preserveBacklogPage) {
    ensureBacklogIssuePage(key);
  }

  if (jiraState.issueDetailRequest && typeof jiraState.issueDetailRequest.abort === "function") {
    jiraState.issueDetailRequest.abort();
  }

  jiraState.expandedIssueKey = key;
  jiraState.issueAccordionCollapsed = false;
  syncIssueAccordionState();
  jiraState.pendingIssueKey = key;

  if (jiraState.issueModalKey === key) {
    renderIssueModal({ issue_key: key, summary: "" }, {
      issue_key: key,
      description: `${key} 상세를 불러오는 중이다.`,
      comments: `${key} 최근 코멘트를 불러오는 중이다.`,
    });
  }

  jiraState.issueDetailRequest = $.ajax({
    url: "/api/jira/issue-detail",
    method: "POST",
    contentType: "application/json",
    data: JSON.stringify({
      issue_key: key,
      mock_mode: $("#mock_mode").is(":checked"),
    }),
  })
    .done((data) => {
      if (jiraState.pendingIssueKey !== key) {
        return;
      }
      jiraState.selectedIssueDetail = data;
      fillWorkflow({
        issue_key: data.issue_key,
        issue_summary: data.summary,
      });
      renderIssueDetail(data);
    })
    .fail((xhr) => {
      if (xhr.statusText === "abort") {
        return;
      }
      jiraState.selectedIssueDetail = null;
      if (jiraState.issueModalKey === key) {
        renderIssueModal({ issue_key: key, summary: "" }, {
          issue_key: key,
          description: "이슈 상세를 불러오지 못했다.",
          comments: (xhr.responseJSON && xhr.responseJSON.error) || xhr.responseText || "오류",
        });
      }
    })
    .always(() => {
      if (jiraState.pendingIssueKey === key) {
        jiraState.pendingIssueKey = null;
      }
      jiraState.issueDetailRequest = null;
    });
}

function setSummaryCard(title, value, detail) {
  if (!value && !detail) {
    return "";
  }
  return `
    <section class="summary-card">
      <p class="summary-card__title">${escapeHtml(title)}</p>
      <strong>${escapeHtml(value || "-")}</strong>
      ${detail ? `<span>${escapeHtml(detail)}</span>` : ""}
    </section>
  `;
}

function eventLogText(events) {
  const items = (events || [])
    .filter((event) => VISIBLE_WORKFLOW_PHASES.has(String(event.phase || "")))
    .slice(-16);
  if (!items.length) {
    return "실행 로그 없음";
  }
  return items
    .map((event) => {
      const phase = String(event.phase || "");
      const label = WORKFLOW_PHASE_LABELS[phase] || phase || "Log";
      return `[${event.timestamp}] ${label}: ${event.message}`;
    })
    .join("\n");
}

function latestWorkflowEvent(data) {
  const events = ((data && data.events) || []).filter((event) => VISIBLE_WORKFLOW_PHASES.has(String(event.phase || "")));
  return events.length ? events[events.length - 1] : null;
}

function workflowElapsedLabel(data) {
  if (!data || !data.started_at) {
    return "-";
  }
  const started = Date.parse(data.started_at);
  const finished = data.finished_at ? Date.parse(data.finished_at) : Date.now();
  if (Number.isNaN(started) || Number.isNaN(finished) || finished < started) {
    return "-";
  }
  const seconds = Math.max(Math.round((finished - started) / 1000), 0);
  const minutes = Math.floor(seconds / 60);
  const remain = seconds % 60;
  if (minutes > 0) {
    return `${minutes}분 ${remain}초`;
  }
  return `${remain}초`;
}

function setAutomationResultHint(text) {
  $("#automation_result_hint").text(String(text || DEFAULT_AUTOMATION_RESULT_HINT));
}

function setAutomationResultPanelOpen(open) {
  const nextOpen = open !== false;
  workflowState.resultPanelOpen = nextOpen;
  $("#automation_result_body").prop("hidden", !nextOpen);
  $("#toggle_automation_result")
    .attr("aria-expanded", nextOpen ? "true" : "false")
    .text(nextOpen ? "접기" : "펼치기");
}

function showAutomationResultPanel(open) {
  $("#automation_result_section").prop("hidden", false);
  if (typeof open === "boolean") {
    setAutomationResultPanelOpen(open);
    return;
  }
  setAutomationResultPanelOpen(workflowState.resultPanelOpen);
}

function hideAutomationResultPanel() {
  $("#automation_result_section").prop("hidden", true);
  setAutomationResultPanelOpen(false);
  setAutomationResultHint(DEFAULT_AUTOMATION_RESULT_HINT);
}

function syncAutomationResultPanel(data) {
  const payload = (data && (data.result || data.error || data)) || {};
  const status = data && data.status ? String(data.status) : String(payload.status || "");
  const message = String((data && data.message) || payload.message || "").trim();
  let hint = DEFAULT_AUTOMATION_RESULT_HINT;

  if (status === "queued") {
    hint = "Codex 자동 작업 요청을 접수했습니다.";
  } else if (status === "running") {
    hint = message || "Codex 자동 작업이 진행 중입니다.";
  } else if (status === "completed") {
    hint = message || "Codex 자동 작업이 완료되었습니다.";
  } else if (status === "failed") {
    hint = message || "Codex 자동 작업이 실패했습니다.";
  } else if (message) {
    hint = message;
  }

  showAutomationResultPanel();
  setAutomationResultHint(hint);
}

function stopWorkflowPolling() {
  if (workflowState.pollTimer) {
    window.clearTimeout(workflowState.pollTimer);
    workflowState.pollTimer = null;
  }
}

function scheduleWorkflowPoll(runId, button) {
  stopWorkflowPolling();
  workflowState.activeRunId = runId;
  workflowState.pollTimer = window.setTimeout(() => {
    $.getJSON(`/api/workflow/run/${encodeURIComponent(runId)}`)
      .done((data) => {
        const payload = data.result || data.error || {};
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", payload.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);

        if (data.status === "completed" || data.status === "failed") {
          stopWorkflowPolling();
          workflowState.activeRunId = null;
          button.prop("disabled", false).text("Codex 자동 작업 실행");
          return;
        }
        scheduleWorkflowPoll(runId, button);
      })
      .fail((xhr) => {
        stopWorkflowPolling();
        workflowState.activeRunId = null;
        button.prop("disabled", false).text("Codex 자동 작업 실행");
        const data = xhr.status === 404
          ? {
            ok: false,
            error: "workflow_run_not_found",
            message: "서버가 재시작되었거나 실행 상태를 복구하지 못했습니다. 자동 작업을 다시 실행해 주세요.",
          }
          : (xhr.responseJSON || { ok: false, error: xhr.responseText });
        setResult("#workflow_result", data);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
      });
  }, 1500);
}

function renderAutomationResult(data) {
  const payload = data.result || data.error || data;
  const modelLabel = payload.resolved_model || payload.requested_model || payload.codex_default_model || "Codex CLI default";
  const reasoningLabel = payload.resolved_reasoning_effort || payload.requested_reasoning_effort || payload.codex_default_reasoning_effort || "Codex CLI default";
  const latestEvent = latestWorkflowEvent(data);
  const cards = [
    setSummaryCard("상태", data.status || payload.status || "-", data.message || payload.message || ""),
    setSummaryCard("현재 단계", latestEvent ? latestEvent.phase : "-", latestEvent ? latestEvent.message : ""),
    setSummaryCard("경과 시간", workflowElapsedLabel(data), payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초 / 테스트 ${payload.test_elapsed_seconds == null ? "-" : `${payload.test_elapsed_seconds}초`}` : ""),
    setSummaryCard("모델", modelLabel, `reasoning: ${reasoningLabel}`),
    setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치: ${payload.current_branch}` : ""),
    setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
    setSummaryCard("테스트", payload.test_returncode == null ? "-" : String(payload.test_returncode), payload.test_command || ""),
    setSummaryCard("Recent Progress", payload.codex_last_progress_message || "-", payload.codex_progress_event_count ? `events: ${payload.codex_progress_event_count}` : ""),
  ].join("");

  $("#automation_overview").html(cards);
  $("#automation_intent").text(payload.model_intent || "응답 없음");
  $("#automation_implementation").text(payload.implementation_summary || "응답 없음");
  $("#automation_validation").text(payload.validation_summary || "응답 없음");

  const risks = payload.risks || [];
  $("#automation_risks").html(
    risks.length
      ? risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")
      : '<li class="file-list__empty">특이 리스크가 보고되지 않았습니다.</li>'
  );

  const files = payload.processed_files || [];
  $("#automation_files").html(
    files.length
      ? files.map((file) => `<li>${escapeHtml(file)}</li>`).join("")
      : '<li class="file-list__empty">변경 파일이 없습니다.</li>'
  );

  $("#automation_diff").text(payload.diff || "diff 없음");
  $("#automation_test_output").text(payload.test_output || "테스트 출력 없음");
  $("#automation_log").text(eventLogText(data.events));
  syncAutomationResultPanel(data);
}

function resetAutomationResult() {
  $("#automation_overview").empty();
  $("#automation_intent").text("자동 작업 실행 후 표시됩니다.");
  $("#automation_implementation").text("자동 작업 실행 후 표시됩니다.");
  $("#automation_validation").text("자동 작업 실행 후 표시됩니다.");
  $("#automation_risks").html('<li class="file-list__empty">자동 작업 실행 후 표시됩니다.</li>');
  $("#automation_files").html('<li class="file-list__empty">자동 작업 실행 후 표시됩니다.</li>');
  $("#automation_diff").text("");
  $("#automation_test_output").text("");
  $("#automation_log").text("");
}

function compactWorkflowEvents(events) {
  const filtered = (events || [])
    .filter((event) => VISIBLE_WORKFLOW_PHASES.has(String(event.phase || "")))
    .map((event) => ({
      ...event,
      phase: String(event.phase || ""),
      message: String(event.message || "").trim(),
    }))
    .filter((event) => event.message);

  const deduped = [];
  filtered.forEach((event) => {
    const last = deduped[deduped.length - 1];
    if (last && last.phase === event.phase && last.message === event.message) {
      deduped[deduped.length - 1] = event;
      return;
    }
    deduped.push(event);
  });

  return deduped.slice(-MAX_VISIBLE_WORKFLOW_EVENTS);
}

function eventLogText(events) {
  const items = compactWorkflowEvents(events);
  if (!items.length) {
    return "표시할 진행 로그가 없습니다.";
  }
  return items
    .map((event) => {
      const label = WORKFLOW_PHASE_LABELS[event.phase] || event.phase || "로그";
      return `[${event.timestamp}] ${label}: ${event.message}`;
    })
    .join("\n");
}

function latestWorkflowEvent(data) {
  const events = compactWorkflowEvents((data && data.events) || []);
  return events.length ? events[events.length - 1] : null;
}

function renderAutomationResult(data) {
  const payload = data.result || data.error || data;
  const modelLabel = payload.resolved_model || payload.requested_model || payload.codex_default_model || "Codex CLI default";
  const reasoningLabel = payload.resolved_reasoning_effort || payload.requested_reasoning_effort || payload.codex_default_reasoning_effort || "Codex CLI default";
  const latestEvent = latestWorkflowEvent(data);
  const testSummaryValue = payload.test_skipped
    ? "자동 실행 안 함"
    : (payload.test_returncode == null ? "-" : String(payload.test_returncode));
  const testSummaryDetail = payload.test_skipped
    ? (payload.test_command || "참고용 명령 없음")
    : (payload.test_command || "");
  const cards = [
    setSummaryCard("상태", data.status || payload.status || "-", data.message || payload.message || ""),
    setSummaryCard("현재 단계", latestEvent ? (WORKFLOW_PHASE_LABELS[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
    setSummaryCard("경과 시간", workflowElapsedLabel(data), payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초` : ""),
    setSummaryCard("모델", modelLabel, `reasoning: ${reasoningLabel}`),
    setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
    setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
    setSummaryCard("로컬 테스트", testSummaryValue, testSummaryDetail),
    setSummaryCard("최근 진행", payload.codex_last_progress_message || "-", payload.codex_progress_event_count ? `이벤트 ${payload.codex_progress_event_count}건` : ""),
  ].join("");

  $("#automation_overview").html(cards);
  $("#automation_intent").text(payload.model_intent || "응답 없음");
  $("#automation_implementation").text(payload.implementation_summary || "응답 없음");
  $("#automation_validation").text(payload.validation_summary || "응답 없음");

  const risks = payload.risks || [];
  $("#automation_risks").html(
    risks.length
      ? risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")
      : '<li class="file-list__empty">특이 리스크가 보고되지 않았습니다.</li>'
  );

  const files = payload.processed_files || [];
  $("#automation_files").html(
    files.length
      ? files.map((file) => `<li>${escapeHtml(file)}</li>`).join("")
      : '<li class="file-list__empty">변경 파일이 없습니다.</li>'
  );

  $("#automation_diff").text(payload.diff || "diff 없음");
  $("#automation_test_output").text(payload.test_output || "테스트 출력 없음");
  $("#automation_log").text(eventLogText(data.events));
}

function renderAutomationResult(data) {
  const payload = data.result || data.error || data;
  const modelLabel = payload.resolved_model || payload.requested_model || payload.codex_default_model || "Codex CLI default";
  const reasoningLabel = payload.resolved_reasoning_effort || payload.requested_reasoning_effort || payload.codex_default_reasoning_effort || "Codex CLI default";
  const latestEvent = latestWorkflowEvent(data);
  const syntaxReturncode = payload.syntax_check_returncode != null ? payload.syntax_check_returncode : payload.test_returncode;
  const syntaxOutput = payload.syntax_check_output || payload.test_output || "";
  const syntaxElapsed = payload.syntax_check_elapsed_seconds != null ? payload.syntax_check_elapsed_seconds : payload.test_elapsed_seconds;
  const syntaxFiles = payload.syntax_checked_files || [];
  const syntaxDetail = syntaxFiles.length ? `파일 ${syntaxFiles.length}개` : (payload.test_command || "지원되는 문법 검사 대상 없음");
  const cards = [
    setSummaryCard("상태", data.status || payload.status || "-", data.message || payload.message || ""),
    setSummaryCard("현재 단계", latestEvent ? (WORKFLOW_PHASE_LABELS[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
    setSummaryCard("경과 시간", workflowElapsedLabel(data), payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초 / 문법 ${syntaxElapsed == null ? "-" : `${syntaxElapsed}초`}` : ""),
    setSummaryCard("모델", modelLabel, `reasoning: ${reasoningLabel}`),
    setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
    setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
    setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxDetail),
    setSummaryCard("최근 진행", payload.codex_last_progress_message || "-", payload.codex_progress_event_count ? `이벤트 ${payload.codex_progress_event_count}건` : ""),
  ].join("");

  $("#automation_overview").html(cards);
  $("#automation_intent").text(payload.model_intent || "응답 없음");
  $("#automation_implementation").text(payload.implementation_summary || "응답 없음");
  $("#automation_validation").text(payload.validation_summary || "응답 없음");

  const risks = payload.risks || [];
  $("#automation_risks").html(
    risks.length
      ? risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")
      : '<li class="file-list__empty">특이 리스크가 보고되지 않았습니다.</li>'
  );

  const files = payload.processed_files || [];
  $("#automation_files").html(
    files.length
      ? files.map((file) => `<li>${escapeHtml(file)}</li>`).join("")
      : '<li class="file-list__empty">변경 파일이 없습니다.</li>'
  );

  $("#automation_diff").text(payload.diff || "diff 없음");
  $("#automation_test_output").text(syntaxOutput || "문법 검사 출력 없음");
  $("#automation_log").text(eventLogText(data.events));
}

function eventLogText(events) {
  const items = compactWorkflowEvents(events);
  if (!items.length) {
    return "표시할 진행 로그가 없습니다.";
  }
  return items
    .map((event) => {
      const label = WORKFLOW_PHASE_LABELS[event.phase] || event.phase || "로그";
      return `[${event.timestamp}] ${label}: ${event.message}`;
    })
    .join("\n");
}

function latestWorkflowEvent(data) {
  const events = compactWorkflowEvents((data && data.events) || []);
  return events.length ? events[events.length - 1] : null;
}

function jiraCommentSyncEntries(syncData) {
  return [
    { key: "questions", title: "사전 질문 코멘트", payload: syncData && syncData.questions ? syncData.questions : null },
    { key: "answers", title: "사용자 답변 코멘트", payload: syncData && syncData.answers ? syncData.answers : null },
  ];
}

function jiraCommentSyncBadge(sync) {
  const status = String((sync && sync.status) || "idle");
  if (status === "created") {
    return { text: "작성 완료", className: "is-created" };
  }
  if (status === "failed") {
    return { text: "동기화 실패", className: "is-failed" };
  }
  if (status === "skipped") {
    return { text: "재사용", className: "is-skipped" };
  }
  return { text: "대기 중", className: "is-idle" };
}

function jiraCommentSyncDetail(sync) {
  const reason = String((sync && sync.reason) || "").trim();
  if (!reason) {
    return String((sync && sync.details) || "").trim();
  }

  const reasonMap = {
    already_synced: "같은 내용의 Jira 코멘트가 이미 있어 기존 코멘트를 재사용했습니다.",
    no_questions: "추가 질문이 없어 Jira 코멘트를 남기지 않았습니다.",
    no_answers: "동기화할 사용자 답변이 없어 Jira 코멘트를 남기지 않았습니다.",
    jira_config_not_found: "Jira 설정이 없어 코멘트를 남기지 못했습니다.",
    request_failed: "Jira API 호출에 실패했습니다.",
    jira_comment_create_failed: "Jira 코멘트 생성에 실패했습니다.",
    not_requested: "아직 동기화를 시도하지 않았습니다.",
  };
  return reasonMap[reason] || String((sync && sync.details) || reason);
}

function renderJiraCommentSync(listSelector, panelSelector, syncData) {
  const entries = jiraCommentSyncEntries(syncData).filter((entry) => {
    if (!entry.payload) {
      return false;
    }
    return !(entry.payload.status === "skipped" && entry.payload.reason === "not_requested");
  });
  if (!entries.length) {
    $(panelSelector).prop("hidden", true);
    $(listSelector).empty();
    return;
  }

  const cards = entries.map((entry) => {
    const sync = entry.payload || {};
    const badge = jiraCommentSyncBadge(sync);
    const detail = jiraCommentSyncDetail(sync);
    const actions = [];
    if (sync.comment_url) {
      actions.push(`<a class="sync-status-link" href="${escapeHtml(sync.comment_url)}" target="_blank" rel="noreferrer">코멘트 보기</a>`);
    }
    if (sync.issue_url) {
      actions.push(`<a class="sync-status-link" href="${escapeHtml(sync.issue_url)}" target="_blank" rel="noreferrer">이슈 열기</a>`);
    }
    return `
      <article class="sync-status-item">
        <div class="sync-status-item__meta">
          <strong class="sync-status-item__title">${escapeHtml(entry.title)}</strong>
          <span class="sync-status-badge ${badge.className}">${escapeHtml(badge.text)}</span>
        </div>
        <div class="sync-status-item__detail">${escapeHtml(detail || "상세 정보가 없습니다.")}</div>
        ${actions.length ? `<div class="sync-status-item__actions">${actions.join("")}</div>` : ""}
      </article>
    `;
  }).join("");

  $(listSelector).html(cards);
  $(panelSelector).prop("hidden", false);
}

function renderWorkflowClarificationSync(data) {
  renderJiraCommentSync(
    "#workflow_clarification_sync_list",
    "#workflow_clarification_sync",
    data && data.jira_comment_sync ? data.jira_comment_sync : null
  );
}

function renderAutomationSync(data) {
  const payload = data.result || data.error || data;
  const syncData = data.jira_comment_sync || payload.jira_comment_sync || workflowState.lastJiraCommentSync || null;
  workflowState.lastJiraCommentSync = syncData;
  renderJiraCommentSync("#automation_sync_status_list", "#automation_sync_status_card", syncData);
}

function renderAutomationResult(data) {
  const payload = data.result || data.error || data;
  const modelLabel = payload.resolved_model || payload.requested_model || payload.codex_default_model || "Codex CLI default";
  const reasoningLabel = payload.resolved_reasoning_effort || payload.requested_reasoning_effort || payload.codex_default_reasoning_effort || "Codex CLI default";
  const latestEvent = latestWorkflowEvent(data);
  const syntaxReturncode = payload.syntax_check_returncode != null ? payload.syntax_check_returncode : payload.test_returncode;
  const syntaxOutput = payload.syntax_check_output || payload.test_output || "";
  const syntaxElapsed = payload.syntax_check_elapsed_seconds != null ? payload.syntax_check_elapsed_seconds : payload.test_elapsed_seconds;
  const syntaxFiles = payload.syntax_checked_files || [];
  const syntaxDetail = syntaxFiles.length ? `대상 파일 ${syntaxFiles.length}개` : (payload.test_command || "지정된 문법 검사 명령이 없습니다.");
  const cards = [
    setSummaryCard("상태", data.status || payload.status || "-", data.message || payload.message || ""),
    setSummaryCard("현재 단계", latestEvent ? (WORKFLOW_PHASE_LABELS[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
    setSummaryCard("경과 시간", workflowElapsedLabel(data), payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초 / 문법 ${syntaxElapsed == null ? "-" : `${syntaxElapsed}초`}` : ""),
    setSummaryCard("모델", modelLabel, `reasoning: ${reasoningLabel}`),
    setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
    setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
    setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxDetail),
    setSummaryCard("최근 진행", payload.codex_last_progress_message || "-", payload.codex_progress_event_count ? `이벤트 ${payload.codex_progress_event_count}건` : ""),
  ].join("");

  $("#automation_overview").html(cards);
  $("#automation_intent").text(payload.model_intent || "응답 없음");
  $("#automation_implementation").text(payload.implementation_summary || "응답 없음");
  $("#automation_validation").text(payload.validation_summary || "응답 없음");

  const risks = payload.risks || [];
  $("#automation_risks").html(
    risks.length
      ? risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")
      : '<li class="file-list__empty">특이 리스크가 보고되지 않았습니다.</li>'
  );

  const files = payload.processed_files || [];
  $("#automation_files").html(
    files.length
      ? files.map((file) => `<li>${escapeHtml(file)}</li>`).join("")
      : '<li class="file-list__empty">변경 파일이 없습니다.</li>'
  );

  $("#automation_diff").text(payload.diff || "diff 없음");
  $("#automation_test_output").text(syntaxOutput || "문법 검사 출력이 없습니다.");
  $("#automation_log").text(eventLogText(data.events));
  renderAutomationSync(data);
}

function resetAutomationResult() {
  workflowState.lastJiraCommentSync = null;
  $("#automation_overview").empty();
  $("#automation_intent").text("자동 작업 실행 후 표시합니다.");
  $("#automation_implementation").text("자동 작업 실행 후 표시합니다.");
  $("#automation_validation").text("자동 작업 실행 후 표시합니다.");
  $("#automation_risks").html('<li class="file-list__empty">자동 작업 실행 후 표시합니다.</li>');
  $("#automation_files").html('<li class="file-list__empty">자동 작업 실행 후 표시합니다.</li>');
  $("#automation_diff").text("");
  $("#automation_test_output").text("");
  $("#automation_log").text("");
  renderJiraCommentSync("#automation_sync_status_list", "#automation_sync_status_card", null);
}

function withButtonBusy(button, callback) {
  const originalText = button.text();
  button.prop("disabled", true).text("실행 중...");
  const done = () => button.prop("disabled", false).text(originalText);
  callback(done);
}

$(document).ready(function () {
  getSetupGuide();
  resetAutomationResult();
  hideAutomationResultPanel();
  clearWorkflowClarification();
  resetIssueDetail();
  renderRepoMappings(parseRepoMappingsText($("#repo_mappings").val()));
  setGithubTokenHelp(false);
  setSavedSecretState("#jira_api_token", false, "현재 저장된 토큰이 있습니다.", "Jira API Token");
  const workflowBatchActions = $("#workflow_batch_actions");
  if (workflowBatchActions.length) {
    workflowBatchActions
      .insertBefore($("#allow_auto_commit").closest(".actions"))
      .append($("#check_repo"), $("#prepare_workflow"), $("#run_automation"));
    $(".card-header__actions").filter(function () {
      return !$(this).children().length;
    }).remove();
  }

  FIELD_LABELS.local_repo_path = "공간별 로컬 저장소 경로";
  $("#mapping_space_key").attr("placeholder", "예: GCPPLDCAD");
  $("#mapping_base_branch").attr("placeholder", "기본 브랜치").val("");
  $("#mapping_local_repo_path").attr("placeholder", "로컬 저장소 경로");
  $("#mapping_github_token").attr("placeholder", "공간 전용 GitHub Token");
  $("#add_repo_mapping").text("연결 추가");
  $(".card-header__copy h2").first().text("1. Jira와 공간 설정");
  $("#allow_auto_commit").closest("label").contents().last()[0].textContent = " 로컬 테스트 없이 자동 커밋 허용";
  $("#repo_mappings").closest("label").contents().first()[0].textContent = "공간별 저장소 연결";
  if (!$(".repo-mapping-section-title").length) {
    $("<div>", { class: "repo-mapping-section-title", text: "1. Jira 공간 키" }).insertBefore("#mapping_space_key");
    $("<div>", { class: "repo-mapping-section-title", text: "2. 연결할 저장소" }).insertBefore("#mapping_repo_owner");
  }
  $("#jira_issue_comments").closest(".detail-card").find("h3").text("최근 코멘트");
  $("#jira_issue_description").closest(".detail-card").find("h3").text("선택 이슈 상세");
  $("#automation_test_output").closest(".detail-card").find("h3").text("문법 검사 출력");
  const sectionTitles = $(".repo-mapping-section-title");
  if (sectionTitles.length >= 2) {
    $(sectionTitles[0]).text("1. Jira 공간 키");
    $(sectionTitles[1]).text("2. 연결할 저장소");
  }
  $("#jira_base_url, #jira_email, #jira_api_token, #jira_jql").on("input change", function () {
    setSavedSecretState("#jira_api_token", hasSavedSecret("#jira_api_token"), "현재 저장된 토큰이 있습니다.", "Jira API Token");
    updateConfigFlowState();
  });
  $(document).on("toggle", "[data-config-panel]", function () {
    const panelKey = String($(this).attr("data-config-panel") || "").trim();
    if ($(this).prop("open")) {
      $("[data-config-panel]").not(this).prop("open", false);
    }
    updateConfigFlowState();
    requestWorkspaceShellHeightSync(false);
  });
  $(document).on("toggle", "#repo_mapping_settings_panel, #repo_mapping_edit_settings_panel", function () {
    requestWorkspaceShellHeightSync(false);
  });
  updateConfigFlowState();
  bindWorkspaceShellHeightObserver();
  setWorkspaceView("prepare");
  window.setTimeout(() => {
    requestWorkspaceShellHeightSync(false);
  }, 0);

  $("#show_operations_view").on("click", function () {
    setWorkspaceView("operations");
  });

  $("#show_prepare_view").on("click", function () {
    setWorkspaceView("prepare");
  });

  $(document).on("click", "[data-jira-backlog-page]", function () {
    setBacklogPage(Number($(this).attr("data-jira-backlog-page")));
  });

  $(window).on("resize", function () {
    if (workspaceState.backlogResizeTimer) {
      window.clearTimeout(workspaceState.backlogResizeTimer);
    }
    workspaceState.backlogResizeTimer = window.setTimeout(() => {
      refreshBacklogLayout();
      requestWorkspaceShellHeightSync(false);
    }, 140);
  });

  $("#open_setup_guide").on("click", function () {
    openGuide("jira", "jira-base-url");
  });

  $("#close_setup_guide").on("click", function () {
    closeGuide();
  });

  $("#close_repo_mapping_modal, #cancel_repo_mapping_edit").on("click", function () {
    closeRepoMappingModal();
  });

  $(document).on("click", "[data-close-config-panel]", function () {
    closeConfigPanel($(this).attr("data-close-config-panel"));
  });

  $("#toggle_automation_result").on("click", function () {
    setAutomationResultPanelOpen(!workflowState.resultPanelOpen);
  });

  $(document).on("click", "[data-close-guide='true']", function () {
    closeGuide();
  });

  $(document).on("click", "[data-close-repo-mapping-modal='true']", function () {
    closeRepoMappingModal();
  });

  $(document).on("click", ".js-open-guide", function () {
    openGuide($(this).attr("data-guide-section"), $(this).attr("data-guide-step-id"));
  });

  $("#repo_mapping_edit_form").on("submit", function (event) {
    event.preventDefault();
    saveRepoMappingModal();
  });

  $("#repo_mapping_edit_github_token").on("input", function () {
    if (!repoMappingState.editingDraft) {
      return;
    }
    syncRepoMappingEditDraftFromForm();
    updateRepoMappingModalTokenControls();
  });

  $("#repo_mapping_edit_toggle_token").on("click", function () {
    const draft = syncRepoMappingEditDraftFromForm();
    if (!draft) {
      return;
    }

    if (draft.github_token) {
      draft.github_token = "";
      $("#repo_mapping_edit_github_token").val("");
    } else if (draft.clear_saved_token) {
      draft.clear_saved_token = false;
    } else if (draft.has_saved_token) {
      draft.clear_saved_token = true;
    }

    repoMappingState.editingDraft = { ...draft };
    updateRepoMappingModalTokenControls();
  });

  $(document).on("click", "[data-guide-tab='true']", function () {
    const sectionId = $(this).attr("data-guide-section");
    const section = findSection(sectionId);
    guideState.activeSectionId = sectionId;
    guideState.activeStepId = section && section.steps.length ? section.steps[0].id : null;
    renderGuide();
  });

  $(document).on("click", "[data-guide-step='true']", function () {
    guideState.activeSectionId = $(this).attr("data-guide-section");
    guideState.activeStepId = $(this).attr("data-guide-step-id");
    renderGuide();
  });

  $(document).on("click", ".js-highlight-fields", function () {
    const target = normalizeGuideTarget($(this).attr("data-guide-section"), $(this).attr("data-guide-step-id"));
    if (target.step) {
      focusFields(target.step.target_fields);
    }
  });

  $(document).on("keydown", function (event) {
    if (event.key !== "Escape") {
      return;
    }
    if ($("#repo_mapping_modal").hasClass("is-open")) {
      closeRepoMappingModal();
      return;
    }
    if ($("#jira_issue_modal").hasClass("is-open")) {
      closeIssueModal();
      return;
    }
    const openConfigPanelElement = $("[data-config-panel][open]").first();
    if (openConfigPanelElement.length) {
      closeConfigPanel(openConfigPanelElement.attr("data-config-panel"));
      return;
    }
    if ($("#setup_guide_modal").hasClass("is-open")) {
      closeGuide();
    }
  });

  $(document).on("change", "input[name='selected_issue']", function () {
    jiraState.expandedIssueKey = String($(this).data("key") || "").trim();
    jiraState.issueAccordionCollapsed = false;
    syncIssueAccordionState();
    const issue = selectedIssue();
    if (issue) {
      fillWorkflow(issue);
      loadIssueDetail(issue.issue_key, { preserveBacklogPage: true });
    }
  });

  $(document).on("click", "[data-jira-issue-modal-open]", function () {
    const item = $(this).closest(".jira-backlog-item");
    const input = item.find("input[name='selected_issue'], input[name='selected_issues']").first();
    if (!input.length) {
      return;
    }
    const issue = {
      issue_key: String($(this).attr("data-jira-issue-modal-open") || input.data("key") || "").trim(),
      issue_summary: String($(this).attr("data-issue-summary") || input.data("summary") || "").trim(),
    };
    if (!input.is(":checked")) {
      input.prop("checked", true).trigger("change");
    } else if (issue.issue_key) {
      fillWorkflow(issue);
    }
    if (issue.issue_key) {
      openIssueModal(issue.issue_key, issue.issue_summary);
      loadIssueDetail(issue.issue_key, { preserveBacklogPage: true });
    }
  });

  $(document).on("keydown", "[data-jira-issue-modal-open]", function (event) {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    $(this).trigger("click");
  });

  $(document).on("click", "[data-close-jira-issue]", function () {
    closeIssueModal();
  });

  $("#add_repo_mapping").on("click", function () {
    const nextItem = readRepoMappingInputs();
    const missing = Object.entries(nextItem).filter(([, value]) => !String(value || "").trim());
    if (missing.length) {
      setResult("#config_result", {
        ok: false,
        error: "repo_mapping_fields_missing",
        fields: missing.map(([key]) => key),
        message: "공간명, owner, repo, base branch, local path를 모두 입력해 주세요.",
      });
      return;
    }

    const items = currentRepoMappings().filter((item) => item.space_key !== nextItem.space_key);
    items.push(nextItem);
    renderRepoMappings(items);
    clearRepoMappingInputs();
    setResult("#config_result", { ok: true, message: `매핑을 추가했습니다: ${nextItem.space_key}` });
  });

  $(document).on("click", "[data-repo-mapping-remove]", function () {
    const removeIndex = Number($(this).attr("data-repo-mapping-remove"));
    const items = currentRepoMappings().filter((_, index) => index !== removeIndex);
    renderRepoMappings(items);
  });

  $("#load_config").on("click", function () {
    $.getJSON("/api/config")
      .done((data) => {
        fillConfig(data);
        clearResultActions("#config_result_actions");
        setResult("#config_result", { ok: true, message: "저장된 설정을 불러왔습니다." });
      })
      .fail((xhr) => {
        clearResultActions("#config_result_actions");
        setResult("#config_result", { ok: false, error: xhr.responseText });
      });
  });

  $("#validate_config").on("click", function () {
    $.ajax({
      url: "/api/config/validate",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(collectConfig()),
    })
      .done((data) => {
        setResult("#config_result", data);
        renderCallout("#config_result_actions", data.valid ? [] : data.requested_information);
      })
      .fail((xhr) => {
        clearResultActions("#config_result_actions");
        setResult("#config_result", { ok: false, error: xhr.responseText });
      });
  });

  $("#save_config").on("click", function () {
    $.ajax({
      url: "/api/config/save",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(collectConfig()),
    })
      .done((data) => {
        const savedTokenSpaces = new Set((data.repo_mapping_token_spaces || []).map((item) => String(item || "").trim().toUpperCase()));
        const refreshedItems = currentRepoMappings().map((item) => ({
          ...item,
          github_token: "",
          has_saved_token: savedTokenSpaces.has(item.space_key),
          clear_saved_token: false,
        }));
        renderRepoMappings(refreshedItems);
        $("#jira_api_token").val("");
        setSavedSecretState("#jira_api_token", Boolean(data.jira_api_token_saved), "현재 저장된 토큰이 있습니다.", "Jira API Token");
        $("#github_token").val("");
        setGithubTokenHelp(savedTokenSpaces.size > 0);
        clearResultActions("#config_result_actions");
        setResult("#config_result", data);
      })
      .fail((xhr) => {
        clearResultActions("#config_result_actions");
        setResult("#config_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  });

  $("#load_backlog").on("click", function () {
    $.ajax({
      url: "/api/jira/backlog",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({}),
    })
      .done((data) => {
        setupIssueTable(data);
        setResult("#backlog_result", data);
      })
      .fail((xhr) => {
        $("#issue_table").empty();
        resetIssueDetail("이슈 상세를 표시할 수 없습니다.");
        setResult("#backlog_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  });

  $("#check_repo").on("click", function () {
    const issue = selectedIssue();
    const issueKey = issue ? issue.issue_key : $("#issue_key").val().trim();
    $.ajax({
      url: "/api/github/check",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ issue_key: issueKey }),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.git_identity_missing_fields ? data.git_identity_missing_fields.map((field) => ({
          field,
          label: fieldLabel(field),
          guide_section: "automation",
          guide_step_id: "automation-git-author",
        })) : []);
      })
      .fail((xhr) => {
        clearResultActions("#workflow_result_actions");
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  });

  $("#prepare_workflow").on("click", function () {
    const issue = selectedIssue();
    if (!issue) {
      setResult("#workflow_result", { ok: false, error: "이슈를 먼저 선택하거나 issue key/summary를 입력해 주세요." });
      return;
    }

    $.ajax({
      url: "/api/workflow/prepare",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(issue),
    })
      .done((data) => {
        fillWorkflow({
          issue_key: data.issue_key,
          issue_summary: data.issue_summary,
          branch_name: data.branch_name,
          commit_message: data.commit_message_template,
        });
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.requested_information);
      })
      .fail((xhr) => setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText }));
  });

  $("#run_automation").on("click", function () {
    const button = $(this);
    const payload = collectWorkflow();
    const missingFields = workflowRequiredFields(payload);

    stopWorkflowPolling();
    resetAutomationResult();
    clearResultActions("#workflow_result_actions");
    if (missingFields.length) {
      const requestedInformation = requestedInfoForFields(missingFields);
      const data = {
        ok: false,
        error: "workflow_fields_missing",
        fields: missingFields,
        requested_information: requestedInformation,
        message: "필수 입력값이 비어 있어 Codex 실행을 시작하지 않았습니다.",
      };
      setResult("#workflow_result", data);
      renderCallout("#workflow_result_actions", requestedInformation);
      renderAutomationResult(data);
      focusFields([missingFields[0]]);
      return;
    }

    button.prop("disabled", true).text("실행 중...");
    showAutomationResultPanel(true);
    setAutomationResultHint("Codex 자동 작업 요청을 접수했습니다.");
    setResult("#workflow_result", { ok: false, status: "queued", message: "Codex 자동 작업을 접수했습니다." });
    $("#automation_log").text("실행 요청을 전송했습니다.");

    $.ajax({
      url: "/api/workflow/run",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(payload),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
        if (data.run_id) {
          scheduleWorkflowPoll(data.run_id, button);
        } else {
          button.prop("disabled", false).text("Codex 자동 작업 실행");
        }
      })
      .fail((xhr) => {
        const data = xhr.responseJSON || { ok: false, error: xhr.responseText };
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
        button.prop("disabled", false).text("Codex 자동 작업 실행");
      });
  });

  function missingClarificationItems() {
    return (workflowState.clarificationQuestions || []).filter((item) => !String(workflowState.clarificationAnswers[item.field] || "").trim());
  }

  function executeWorkflowRunWithClarification(button, payload) {
    button.prop("disabled", true).text("실행 중...");
    clearWorkflowClarification();
    showAutomationResultPanel(true);
    setAutomationResultHint("Codex 자동 작업 요청을 접수했습니다.");
    setResult("#workflow_result", { ok: false, status: "queued", message: "Codex 자동 작업을 접수했습니다." });
    $("#automation_log").text("실행 요청을 전송했습니다.");

    $.ajax({
      url: "/api/workflow/run",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(payload),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
        if (data.run_id) {
          scheduleWorkflowPoll(data.run_id, button);
        } else {
          button.prop("disabled", false).text("Codex 자동 작업 실행");
        }
      })
      .fail((xhr) => {
        const data = xhr.responseJSON || { ok: false, error: xhr.responseText };
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
        button.prop("disabled", false).text("Codex 자동 작업 실행");
      });
  }

  function requestWorkflowClarification(button, payload) {
    button.prop("disabled", true).text("사전 확인 중...");
    clearResultActions("#workflow_result_actions");

    $.ajax({
      url: "/api/workflow/clarify",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(payload),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        if (data.status === "needs_input") {
          renderWorkflowClarification(data);
          button.prop("disabled", false).text("Codex 자동 작업 실행");
          return;
        }

        clearWorkflowClarification();
        executeWorkflowRunWithClarification(button, payload);
      })
      .fail((xhr) => {
        const data = xhr.responseJSON || { ok: false, error: xhr.responseText };
        clearWorkflowClarification();
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.requested_information || []);
        button.prop("disabled", false).text("Codex 자동 작업 실행");
      });
  }

  $(document).on("input", "[data-clarification-answer]", function () {
    syncWorkflowClarificationAnswers();
  });

  $("#dismiss_workflow_clarification").on("click", function () {
    clearWorkflowClarification();
  });

  $("#submit_clarification_answers").on("click", function () {
    syncWorkflowClarificationAnswers();
    const missingClarifications = missingClarificationItems();
    if (missingClarifications.length) {
      setResult("#workflow_result", {
        ok: false,
        error: "clarification_answers_missing",
        fields: missingClarifications.map((item) => item.field),
        message: "추가 확인 질문에 대한 답변을 모두 입력해 주세요.",
      });
      const firstField = missingClarifications[0].field;
      const firstInput = $(`[data-clarification-answer="${firstField}"]`);
      if (firstInput.length) {
        firstInput.trigger("focus");
      }
      return;
    }
    $("#run_automation").trigger("click");
  });

  $("#add_repo_mapping").off("click").on("click", function () {
    const nextItem = readRepoMappingInputs();
    const missing = ["space_key", "repo_owner", "repo_name", "base_branch", "local_repo_path"]
      .filter((key) => !String(nextItem[key] || "").trim());
    if (missing.length) {
      setResult("#config_result", {
        ok: false,
        error: "repo_mapping_fields_missing",
        fields: missing,
        message: "공간명, owner, repo, base branch, local path를 모두 입력해 주세요.",
      });
      return;
    }

    const existing = currentRepoMappings().find((item) => item.space_key === nextItem.space_key);
    const items = currentRepoMappings().filter((item) => item.space_key !== nextItem.space_key);
    items.push({
      ...nextItem,
      has_saved_token: existing ? existing.has_saved_token : false,
      clear_saved_token: false,
    });
    renderRepoMappings(items);
    clearRepoMappingInputs();
    setResult("#config_result", { ok: true, message: `매핑을 추가했습니다: ${nextItem.space_key}` });
  });

  $(document).off("click", "[data-repo-mapping-edit]").on("click", "[data-repo-mapping-edit]", function () {
    const editIndex = Number($(this).attr("data-repo-mapping-edit"));
    openRepoMappingModal(editIndex);
  });

  $(document).off("click", "[data-repo-mapping-remove]").on("click", "[data-repo-mapping-remove]", function () {
    const removeIndex = Number($(this).attr("data-repo-mapping-remove"));
    const items = currentRepoMappings().filter((_, index) => index !== removeIndex);
    renderRepoMappings(items);
  });

$(document).off("click", "[data-repo-mapping-toggle-token]").on("click", "[data-repo-mapping-toggle-token]", function () {
    const toggleIndex = Number($(this).attr("data-repo-mapping-toggle-token"));
    const items = currentRepoMappings();
    const target = items[toggleIndex];
    if (!target) {
      return;
    }

    if (target.clear_saved_token) {
      target.clear_saved_token = false;
    } else if (target.scm_token || target.github_token) {
      target.scm_token = "";
      target.github_token = "";
    } else if (target.has_saved_token) {
      target.clear_saved_token = true;
    }
    renderRepoMappings(items);
  });

  $("#run_automation").off("click").on("click", function () {
    const button = $(this);
    syncWorkflowClarificationAnswers();
    const payload = collectWorkflow();
    const missingFields = workflowRequiredFields(payload);

    stopWorkflowPolling();
    resetAutomationResult();
    hideAutomationResultPanel();
    clearResultActions("#workflow_result_actions");
    if (missingFields.length) {
      const requestedInformation = requestedInfoForFields(missingFields);
      const data = {
        ok: false,
        error: "workflow_fields_missing",
        fields: missingFields,
        requested_information: requestedInformation,
        message: "필수 입력값이 비어 있어 Codex 실행을 시작하지 않습니다.",
      };
      setResult("#workflow_result", data);
      renderCallout("#workflow_result_actions", requestedInformation);
      renderAutomationResult(data);
      focusFields([missingFields[0]]);
      return;
    }

    if (workflowState.clarificationQuestions.length) {
      const missingClarifications = missingClarificationItems();
      if (missingClarifications.length) {
        setResult("#workflow_result", {
          ok: false,
          error: "clarification_answers_missing",
          fields: missingClarifications.map((item) => item.field),
          message: "추가 확인 질문에 대한 답변을 모두 입력해 주세요.",
        });
        const firstField = missingClarifications[0].field;
        const firstInput = $(`[data-clarification-answer="${firstField}"]`);
        if (firstInput.length) {
          firstInput.trigger("focus");
        }
        return;
      }
    }

    requestWorkflowClarification(button, payload);
  });
});

function normalizeScmProvider(value) {
  const provider = String(value || "").trim().toLowerCase();
  return provider === "gitlab" ? "gitlab" : "github";
}

function splitGithubRepoRef(repoRef) {
  const parts = String(repoRef || "").trim().split("/");
  if (parts.length < 2) {
    return { repo_owner: "", repo_name: "" };
  }
  return {
    repo_owner: parts[0].trim(),
    repo_name: parts[parts.length - 1].trim(),
  };
}

function buildRepoRef(provider, repoOwner, repoName, repoRef) {
  if (provider === "gitlab") {
    return String(repoRef || "").trim().replace(/^\/+|\/+$/g, "");
  }
  return [String(repoOwner || "").trim(), String(repoName || "").trim()]
    .filter(Boolean)
    .join("/")
    .replace(/^\/+|\/+$/g, "");
}

function normalizeRepoMappingItem(item) {
  const provider = normalizeScmProvider(item.provider);
  const normalizedRepoRef = buildRepoRef(provider, item.repo_owner, item.repo_name, item.repo_ref);
  const githubParts = provider === "github" ? splitGithubRepoRef(normalizedRepoRef) : { repo_owner: "", repo_name: "" };
  const scmToken = String(item.scm_token || item.github_token || "").trim();
  return {
    space_key: String(item.space_key || "").trim().toUpperCase(),
    provider,
    repo_ref: normalizedRepoRef,
    repo_owner: githubParts.repo_owner,
    repo_name: githubParts.repo_name,
    base_branch: String(item.base_branch || "").trim(),
    local_repo_path: String(item.local_repo_path || "").trim(),
    scm_token: scmToken,
    github_token: scmToken,
    has_saved_token: Boolean(item.has_saved_token),
    clear_saved_token: Boolean(item.clear_saved_token),
  };
}

function repoMappingSettingsSummary(provider) {
  return provider === "gitlab"
    ? "GitLab Base URL을 확인하고 Project Path, 브랜치와 로컬 경로를 입력한다."
    : "GitHub Owner, Repository, 브랜치와 로컬 경로를 입력한다.";
}

function toggleRepoMappingProviderPanels(containerSelector, provider) {
  const normalizedProvider = normalizeScmProvider(provider);
  const container = $(containerSelector);
  container.find("[data-provider-panel]").each(function () {
    const expectedProvider = String($(this).attr("data-provider-panel") || "").trim().toLowerCase();
    if (expectedProvider === "common") {
      $(this).prop("hidden", false);
      return;
    }
    $(this).prop("hidden", expectedProvider !== normalizedProvider);
  });
}

function updateRepoMappingProviderUI(options) {
  const settings = options || {};
  const provider = normalizeScmProvider($("#mapping_provider").val());
  $("#mapping_provider").val(provider);
  toggleRepoMappingProviderPanels("#repo_mapping_settings_panel", provider);
  $("#repo_mapping_settings_summary").text(repoMappingSettingsSummary(provider));
  if (settings.openSettings) {
    $("#repo_mapping_settings_panel").prop("open", true);
  }
  $("#mapping_scm_token").attr(
    "placeholder",
    provider === "gitlab" ? "공간 전용 GitLab Project Access Token" : "공간 전용 GitHub Token",
  );
  setGithubTokenHelp(currentRepoMappings().some((item) => item.has_saved_token && !item.clear_saved_token));
}

function updateRepoMappingEditProviderUI() {
  const provider = normalizeScmProvider($("#repo_mapping_edit_provider").val());
  $("#repo_mapping_edit_provider").val(provider);
  toggleRepoMappingProviderPanels("#repo_mapping_edit_settings_panel", provider);
  $("#repo_mapping_edit_settings_summary").text(repoMappingSettingsSummary(provider));
  $("#repo_mapping_edit_scm_token").attr(
    "placeholder",
    provider === "gitlab" ? "새 GitLab Project Access Token 입력 시 갱신" : "새 GitHub Token 입력 시 갱신",
  );
}

function pickLocalRepoPath(button, inputSelector) {
  const targetInput = $(inputSelector);
  withButtonBusy(button, (done) => {
    $.ajax({
      url: "/api/local-repo-path/pick",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ initial_path: targetInput.val().trim() }),
    })
      .done((data) => {
        if (!data || data.error === "directory_selection_cancelled") {
          done();
          return;
        }
        if (data.ok && data.path) {
          targetInput.val(data.path).trigger("input").trigger("change");
          clearResultActions("#config_result_actions");
          setResult("#config_result", { ok: true, message: "로컬 저장소 경로를 선택했다." });
        } else {
          setResult("#config_result", data);
        }
        done();
      })
      .fail((xhr) => {
        clearResultActions("#config_result_actions");
        setResult("#config_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
        done();
      });
  });
}

parseRepoMappingsText = function (text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.split("|").map((part) => part.trim()))
    .map((parts) => {
      if ((parts.length === 5 || parts.length === 6) && ["github", "gitlab"].includes(String(parts[1] || "").trim().toLowerCase())) {
        return normalizeRepoMappingItem({
          space_key: parts[0],
          provider: parts[1],
          repo_ref: parts[2],
          base_branch: parts[3],
          local_repo_path: parts[4],
          scm_token: parts[5] || "",
        });
      }
      if ((parts.length === 5 || parts.length === 6) && parts.slice(0, 5).every(Boolean)) {
        return normalizeRepoMappingItem({
          space_key: parts[0],
          provider: "github",
          repo_owner: parts[1],
          repo_name: parts[2],
          base_branch: parts[3],
          local_repo_path: parts[4],
          scm_token: parts[5] || "",
        });
      }
      return null;
    })
    .filter(Boolean);
};

serializeRepoMappings = function (items) {
  return (items || [])
    .map((item) => normalizeRepoMappingItem(item))
    .filter((item) => item.space_key && item.provider && item.repo_ref && item.base_branch && item.local_repo_path)
    .map((item) => [item.space_key, item.provider, item.repo_ref, item.base_branch, item.local_repo_path].join("|"))
    .join("\n");
};

repoMappingTokenSummary = function (item) {
  const providerLabel = normalizeScmProvider(item.provider) === "gitlab" ? "GitLab" : "GitHub";
  if (item.clear_saved_token) {
    return `${providerLabel} 토큰 해제 예정`;
  }
  if (item.scm_token || item.github_token) {
    return `${providerLabel} 토큰 새로 입력`;
  }
  if (item.has_saved_token) {
    return `${providerLabel} 토큰 저장됨`;
  }
  return `${providerLabel} 토큰 필요`;
};

renderRepoMappings = function (items) {
  repoMappingState.items = (items || []).map((item) => normalizeRepoMappingItem(item));
  const rows = repoMappingState.items
    .map((item, index) => `
      <div class="repo-mapping-item">
        <div class="repo-mapping-item__summary">
          <strong>${escapeHtml(`공간 ${item.space_key}`)}</strong>
          <span>${escapeHtml(`Provider ${item.provider}`)}</span>
          <span>${escapeHtml(`저장소 ${item.repo_ref}`)}</span>
          <span>${escapeHtml(`기준 브랜치 ${item.base_branch}`)}</span>
          <span>${escapeHtml(`로컬 경로 ${item.local_repo_path}`)}</span>
          <span class="repo-mapping-token-status">${escapeHtml(repoMappingTokenSummary(item))}</span>
        </div>
        <div class="repo-mapping-item__actions">
          <button type="button" class="ghost-button repo-mapping-item__edit" data-repo-mapping-edit="${index}">편집</button>
          <button type="button" class="ghost-button repo-mapping-item__remove" data-repo-mapping-remove="${index}">제거</button>
          ${repoMappingTokenActionButton(item, index)}
        </div>
      </div>
    `)
    .join("");
  $("#repo_mapping_list").html(
    rows || '<div class="repo-mapping-empty-state"><strong>아직 추가한 공간 연결이 없습니다.</strong><p>공간 키와 저장소 설정을 입력한 뒤 연결 추가를 누른다.</p></div>',
  );
  syncRepoMappingsField();
  updateConfigFlowState();
  setGithubTokenHelp(repoMappingState.items.some((item) => item.has_saved_token && !item.clear_saved_token));
};

clearRepoMappingInputs = function () {
  $("#mapping_space_key").val("");
  $("#mapping_provider").val("github");
  $("#mapping_repo_owner").val("");
  $("#mapping_repo_name").val("");
  $("#mapping_repo_ref").val("");
  $("#mapping_base_branch").val("");
  $("#mapping_local_repo_path").val("");
  $("#mapping_scm_token").val("");
  $("#mapping_github_token").val("");
  updateRepoMappingProviderUI();
};

readRepoMappingInputs = function () {
  const provider = normalizeScmProvider($("#mapping_provider").val());
  return normalizeRepoMappingItem({
    space_key: $("#mapping_space_key").val(),
    provider,
    repo_owner: $("#mapping_repo_owner").val(),
    repo_name: $("#mapping_repo_name").val(),
    repo_ref: $("#mapping_repo_ref").val(),
    base_branch: $("#mapping_base_branch").val(),
    local_repo_path: $("#mapping_local_repo_path").val(),
    scm_token: $("#mapping_scm_token").val(),
  });
};

syncRepoMappingEditDraftFromForm = function () {
  if (!repoMappingState.editingDraft) {
    return null;
  }
  const provider = normalizeScmProvider($("#repo_mapping_edit_provider").val());
  const nextToken = $("#repo_mapping_edit_scm_token").val().trim();
  repoMappingState.editingDraft = normalizeRepoMappingItem({
    ...repoMappingState.editingDraft,
    space_key: $("#repo_mapping_edit_space_key").val(),
    provider,
    repo_owner: $("#repo_mapping_edit_repo_owner").val(),
    repo_name: $("#repo_mapping_edit_repo_name").val(),
    repo_ref: $("#repo_mapping_edit_repo_ref").val(),
    base_branch: $("#repo_mapping_edit_base_branch").val(),
    local_repo_path: $("#repo_mapping_edit_local_repo_path").val(),
    scm_token: nextToken,
    has_saved_token: repoMappingState.editingDraft.has_saved_token,
    clear_saved_token: nextToken ? false : Boolean(repoMappingState.editingDraft.clear_saved_token),
  });
  return repoMappingState.editingDraft;
};

updateRepoMappingModalTokenControls = function () {
  const draft = repoMappingState.editingDraft;
  const button = $("#repo_mapping_edit_toggle_token");
  const status = $("#repo_mapping_edit_token_status");
  if (!draft) {
    button.prop("disabled", true).text("저장된 토큰 없음");
    status.text("저장된 토큰 상태를 표시한다.");
    return;
  }
  const providerLabel = draft.provider === "gitlab" ? "GitLab" : "GitHub";
  if (draft.has_saved_token && !draft.clear_saved_token && !(draft.scm_token || draft.github_token)) {
    button.prop("disabled", false).text("저장된 토큰 해제");
    status.text(`현재 저장된 ${providerLabel} 토큰이 있다.`);
    return;
  }
  if (draft.clear_saved_token) {
    button.prop("disabled", false).text("해제 취소");
    status.text(`저장된 ${providerLabel} 토큰을 해제할 예정이다. 새 토큰을 입력하면 해제 대신 교체된다.`);
    return;
  }
  if (draft.scm_token || draft.github_token) {
    button.prop("disabled", false).text("입력 토큰 비우기");
    status.text(`새 ${providerLabel} 토큰을 입력했다. 저장 시 기존 값이 있으면 교체한다.`);
    return;
  }
  if (draft.has_saved_token) {
    button.prop("disabled", false).text("저장된 토큰 해제");
    status.text(`저장된 ${providerLabel} 토큰이 있다.`);
    return;
  }
  button.prop("disabled", true).text("저장된 토큰 없음");
  status.text(`저장된 ${providerLabel} 토큰이 없다.`);
};

clearRepoMappingModal = function () {
  repoMappingState.editingIndex = null;
  repoMappingState.editingDraft = null;
  $("#repo_mapping_edit_form").trigger("reset");
  $("#repo_mapping_edit_provider").val("github");
  updateRepoMappingEditProviderUI();
  updateRepoMappingModalTokenControls();
};

openRepoMappingModal = function (index) {
  const items = currentRepoMappings();
  const target = items[index];
  if (!target) {
    return;
  }
  repoMappingState.editingIndex = index;
  repoMappingState.editingDraft = { ...normalizeRepoMappingItem(target) };
  $("#repo_mapping_edit_space_key").val(target.space_key);
  $("#repo_mapping_edit_provider").val(target.provider || "github");
  $("#repo_mapping_edit_repo_owner").val(target.repo_owner || "");
  $("#repo_mapping_edit_repo_name").val(target.repo_name || "");
  $("#repo_mapping_edit_repo_ref").val(target.repo_ref || "");
  $("#repo_mapping_edit_base_branch").val(target.base_branch || "");
  $("#repo_mapping_edit_local_repo_path").val(target.local_repo_path || "");
  $("#repo_mapping_edit_scm_token").val(target.scm_token || target.github_token || "");
  updateRepoMappingEditProviderUI();
  updateRepoMappingModalTokenControls();
  $("#repo_mapping_modal").addClass("is-open").attr("aria-hidden", "false");
  syncModalBodyState();
  window.setTimeout(() => $("#repo_mapping_edit_space_key").trigger("focus"), 0);
};

saveRepoMappingModal = function () {
  const editIndex = Number(repoMappingState.editingIndex);
  const draft = syncRepoMappingEditDraftFromForm();
  if (!Number.isInteger(editIndex) || editIndex < 0 || !draft) {
    return;
  }
  const missing = ["space_key", "repo_ref", "base_branch", "local_repo_path"].filter((key) => !String(draft[key] || "").trim());
  if (missing.length) {
    setResult("#config_result", {
      ok: false,
      error: "repo_mapping_fields_missing",
      fields: missing,
      message: "공간명, 저장소 경로, 기준 브랜치, 로컬 경로를 모두 입력해 주세요.",
    });
    return;
  }
  const duplicateIndex = currentRepoMappings().findIndex((item, index) => index !== editIndex && item.space_key === draft.space_key);
  if (duplicateIndex >= 0) {
    setResult("#config_result", {
      ok: false,
      error: "repo_mapping_space_key_duplicate",
      field: "space_key",
      message: `이미 등록한 공간이다: ${draft.space_key}`,
    });
    $("#repo_mapping_edit_space_key").trigger("focus");
    return;
  }
  const items = currentRepoMappings();
  items[editIndex] = draft;
  closeRepoMappingModal();
  renderRepoMappings(items);
  setResult("#config_result", { ok: true, message: `매핑을 수정했다: ${draft.space_key}` });
};

setGithubTokenHelp = function (saved) {
  const provider = normalizeScmProvider($("#mapping_provider").val());
  const providerLabel = provider === "gitlab" ? "GitLab Project Access Token" : "GitHub Token";
  const helpText = saved
    ? `저장된 공간 전용 ${providerLabel}이 있다. 새 값을 비우면 기존 저장 토큰을 유지한다.`
    : `공간 연결마다 ${providerLabel}을 저장한다. GitLab은 write_repository scope가 필요하다.`;
  $("#scm_token_help").text(helpText);
};

fillConfig = function (data) {
  const savedTokenSpaces = new Set((data.repo_mapping_token_spaces || []).map((item) => String(item || "").trim().toUpperCase()));
  const repoMappings = parseRepoMappingsText(data.repo_mappings || "").map((item) => ({
    ...item,
    has_saved_token: savedTokenSpaces.has(item.space_key),
  }));
  renderRepoMappings(repoMappings);
  Object.keys(data || {}).forEach((key) => {
    if (["repo_mappings", "repo_mapping_token_spaces", "jira_api_token_saved"].includes(key)) {
      return;
    }
    const el = $("#" + key);
    if (el.length) {
      el.val(data[key]);
    }
  });
  setSavedSecretState("#jira_api_token", Boolean(data.jira_api_token_saved), "현재 저장한 토큰이 있다.", "Jira API Token");
  updateRepoMappingProviderUI();
  setGithubTokenHelp(savedTokenSpaces.size > 0);
  updateConfigFlowState();
};

collectConfig = function () {
  syncRepoMappingsField();
  const repoMappingTokens = {};
  const repoMappingTokenClears = [];
  currentRepoMappings().forEach((item) => {
    const token = String(item.scm_token || item.github_token || "").trim();
    if (token) {
      repoMappingTokens[item.space_key] = token;
      return;
    }
    if (item.clear_saved_token) {
      repoMappingTokenClears.push(item.space_key);
    }
  });
  return {
    jira_base_url: readTextValue("#jira_base_url"),
    jira_email: readTextValue("#jira_email"),
    jira_api_token: readTextValue("#jira_api_token"),
    jira_jql: readTextValue("#jira_jql"),
    gitlab_base_url: readTextValue("#gitlab_base_url"),
    repo_mappings: readTextValue("#repo_mappings"),
    repo_mapping_tokens: repoMappingTokens,
    repo_mapping_token_clears: repoMappingTokenClears,
  };
};

collectWorkflow = function () {
  const issue = selectedIssue();
  const detail = issue && jiraState.selectedIssueDetail && jiraState.selectedIssueDetail.issue_key === issue.issue_key
    ? jiraState.selectedIssueDetail
    : null;
  return {
    issue_key: $("#issue_key").val().trim(),
    issue_summary: $("#issue_summary").val().trim(),
    branch_name: $("#branch_name").val().trim(),
    commit_message: $("#commit_message").val().trim(),
    codex_model: $("#codex_model").val().trim(),
    codex_reasoning_effort: $("#codex_reasoning_effort").val().trim(),
    work_instruction: $("#work_instruction").val().trim(),
    acceptance_criteria: $("#acceptance_criteria").val().trim(),
    test_command: $("#test_command").val().trim(),
    commit_checklist: $("#commit_checklist").val().trim(),
    git_author_name: $("#git_author_name").val().trim(),
    git_author_email: $("#git_author_email").val().trim(),
    issue_status: detail ? (detail.status || "") : "",
    issue_type: detail ? (detail.issue_type || "") : "",
    issue_priority: detail ? (detail.priority || "") : "",
    issue_assignee: detail ? (detail.assignee || "") : "",
    issue_labels: detail ? ((detail.labels || []).join(", ")) : "",
    issue_description: detail ? (detail.description || "") : "",
    issue_comments_text: detail ? (detail.comments_text || "") : "",
    clarification_questions: workflowState.clarificationQuestions.map((item) => ({ ...item })),
    clarification_answers: { ...workflowState.clarificationAnswers },
    allow_auto_commit: $("#allow_auto_commit").is(":checked"),
    allow_auto_push: $("#allow_auto_push").is(":checked"),
  };
};

syncAutomationResultPanel = function (data) {
  const payload = (data && (data.result || data.error || data)) || {};
  const status = data && data.status ? String(data.status) : String(payload.status || "");
  const message = String((data && data.message) || payload.message || "").trim();
  let hint = DEFAULT_AUTOMATION_RESULT_HINT;
  if (status === "queued") {
    hint = "Codex 자동 작업 요청을 접수했다.";
  } else if (status === "running") {
    hint = message || "Codex 자동 작업을 진행 중이다.";
  } else if (status === "completed") {
    hint = message || "Codex 자동 작업을 완료했다.";
  } else if (status === "partially_completed") {
    hint = message || "로컬 작업은 완료했지만 원격 push 단계에서 추가 확인이 필요하다.";
  } else if (status === "failed") {
    hint = message || "Codex 자동 작업이 실패했다.";
  } else if (message) {
    hint = message;
  }
  showAutomationResultPanel();
  setAutomationResultHint(hint);
};

scheduleWorkflowPoll = function (runId, button) {
  stopWorkflowPolling();
  workflowState.activeRunId = runId;
  workflowState.pollTimer = window.setTimeout(() => {
    $.getJSON(`/api/workflow/run/${encodeURIComponent(runId)}`)
      .done((data) => {
        const payload = data.result || data.error || {};
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", payload.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
        if (["completed", "failed", "partially_completed"].includes(String(data.status || "").trim())) {
          stopWorkflowPolling();
          workflowState.activeRunId = null;
          button.prop("disabled", false).text("Codex 자동 작업 실행");
          return;
        }
        scheduleWorkflowPoll(runId, button);
      })
      .fail((xhr) => {
        stopWorkflowPolling();
        workflowState.activeRunId = null;
        button.prop("disabled", false).text("Codex 자동 작업 실행");
        const data = xhr.status === 404 ? { ok: false, error: "workflow_run_not_found" } : (xhr.responseJSON || { ok: false, error: xhr.responseText });
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", data.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
      });
  }, 1500);
};

renderAutomationResult = function (data) {
  const payload = data.result || data.error || data;
  const modelLabel = payload.resolved_model || payload.requested_model || payload.codex_default_model || "Codex CLI default";
  const reasoningLabel = payload.resolved_reasoning_effort || payload.requested_reasoning_effort || payload.codex_default_reasoning_effort || "Codex CLI default";
  const latestEvent = latestWorkflowEvent(data);
  const syntaxReturncode = payload.syntax_check_returncode != null ? payload.syntax_check_returncode : payload.test_returncode;
  const syntaxOutput = payload.syntax_check_output || payload.test_output || "";
  const syntaxElapsed = payload.syntax_check_elapsed_seconds != null ? payload.syntax_check_elapsed_seconds : payload.test_elapsed_seconds;
  const syntaxFiles = payload.syntax_checked_files || [];
  const syntaxDetail = syntaxFiles.length ? `대상 파일 ${syntaxFiles.length}개` : (payload.test_command || "지정한 문법 검사 명령 없음");
  const cards = [
    setSummaryCard("상태", data.status || payload.status || "-", data.message || payload.message || ""),
    setSummaryCard("현재 단계", latestEvent ? (WORKFLOW_PHASE_LABELS[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
    setSummaryCard("경과 시간", workflowElapsedLabel(data), payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초 / 문법 ${syntaxElapsed == null ? "-" : `${syntaxElapsed}초`}` : ""),
    setSummaryCard("모델", modelLabel, `reasoning: ${reasoningLabel}`),
    setSummaryCard("저장소", payload.remote_repo_ref || data.resolved_repo_ref || "-", payload.remote_provider || data.resolved_repo_provider || ""),
    setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
    setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
    setSummaryCard("원격 Push", payload.push_succeeded ? "성공" : (payload.allow_auto_push ? "실패/미실행" : "비활성"), payload.remote_branch || ""),
    setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxDetail),
    setSummaryCard("최근 진행", payload.codex_last_progress_message || "-", payload.codex_progress_event_count ? `이벤트 ${payload.codex_progress_event_count}건` : ""),
  ].join("");
  $("#automation_overview").html(cards);
  $("#automation_intent").text(payload.model_intent || "응답 없음");
  $("#automation_implementation").text(payload.implementation_summary || "응답 없음");
  $("#automation_validation").text(payload.validation_summary || "응답 없음");
  const risks = payload.risks || [];
  $("#automation_risks").html(risks.length ? risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("") : '<li class="file-list__empty">특이 리스크 보고 없음</li>');
  const files = payload.processed_files || [];
  $("#automation_files").html(files.length ? files.map((file) => `<li>${escapeHtml(file)}</li>`).join("") : '<li class="file-list__empty">변경 파일 없음</li>');
  $("#automation_diff").text(payload.diff || "diff 없음");
  $("#automation_test_output").text(syntaxOutput || "문법 검사 출력 없음");
  $("#automation_log").text(eventLogText(data.events));
  renderAutomationSync(data);
};

$(document).ready(function () {
  FIELD_LABELS.gitlab_base_url = "GitLab Base URL";
  FIELD_LABELS.mapping_provider = "SCM Provider";
  FIELD_LABELS.mapping_repo_ref = "Repository Path";
  FIELD_LABELS.mapping_scm_token = "SCM Token";
  FIELD_LABELS.allow_auto_push = "커밋 후 원격 저장소 push";
  VISIBLE_WORKFLOW_PHASES.add("push_start");
  VISIBLE_WORKFLOW_PHASES.add("push_end");
  VISIBLE_WORKFLOW_PHASES.add("push_failed");
  WORKFLOW_PHASE_LABELS.push_start = "원격 Push 시작";
  WORKFLOW_PHASE_LABELS.push_end = "원격 Push 완료";
  WORKFLOW_PHASE_LABELS.push_failed = "원격 Push 실패";

  $(".repo-mapping-section-title").remove();

  $("#mapping_provider").off("change").on("change", function () {
    updateRepoMappingProviderUI({ openSettings: true });
  });
  $("#repo_mapping_edit_provider").off("change").on("change", function () {
    updateRepoMappingEditProviderUI();
    $("#repo_mapping_edit_settings_panel").prop("open", true);
    if (repoMappingState.editingDraft) {
      syncRepoMappingEditDraftFromForm();
      updateRepoMappingModalTokenControls();
    }
  });
  updateRepoMappingProviderUI();
  updateRepoMappingEditProviderUI();

  $("#browse_mapping_local_repo_path").off("click").on("click", function () {
    pickLocalRepoPath($(this), "#mapping_local_repo_path");
  });

  $("#browse_repo_mapping_edit_local_repo_path").off("click").on("click", function () {
    pickLocalRepoPath($(this), "#repo_mapping_edit_local_repo_path");
  });

  $("#add_repo_mapping").off("click").on("click", function () {
    const nextItem = readRepoMappingInputs();
    const missing = ["space_key", "repo_ref", "base_branch", "local_repo_path"].filter((key) => !String(nextItem[key] || "").trim());
    if (missing.length) {
      setResult("#config_result", {
        ok: false,
        error: "repo_mapping_fields_missing",
        fields: missing,
        message: "공간명, 저장소 경로, 기준 브랜치, 로컬 경로를 모두 입력해 주세요.",
      });
      return;
    }
    const existing = currentRepoMappings().find((item) => item.space_key === nextItem.space_key);
    const items = currentRepoMappings().filter((item) => item.space_key !== nextItem.space_key);
    items.push({
      ...nextItem,
      has_saved_token: existing ? existing.has_saved_token : false,
      clear_saved_token: false,
    });
    renderRepoMappings(items);
    clearRepoMappingInputs();
    setResult("#config_result", { ok: true, message: `매핑을 추가했다: ${nextItem.space_key}` });
  });

  $("#check_repo").off("click").on("click", function () {
    const issue = selectedIssue();
    if (!issue) {
      setResult("#workflow_result", { ok: false, error: "issue_selection_required" });
      return;
    }
    withButtonBusy($(this), (done) => {
      $.ajax({
        url: "/api/repo/check",
        method: "POST",
        contentType: "application/json",
        data: JSON.stringify({ issue_key: issue.issue_key }),
      })
        .done((data) => {
          setResult("#workflow_result", data);
          renderCallout("#workflow_result_actions", data.requested_information || []);
          done();
        })
        .fail((xhr) => {
          const data = xhr.responseJSON || { ok: false, error: xhr.responseText };
          setResult("#workflow_result", data);
          renderCallout("#workflow_result_actions", data.requested_information || []);
          done();
        });
    });
  });

  $("#repo_mapping_edit_form").off("submit").on("submit", function (event) {
    event.preventDefault();
    saveRepoMappingModal();
  });

  $("#repo_mapping_edit_scm_token").off("input").on("input", function () {
    if (!repoMappingState.editingDraft) {
      return;
    }
    syncRepoMappingEditDraftFromForm();
    updateRepoMappingModalTokenControls();
  });

  $("#repo_mapping_edit_toggle_token").off("click").on("click", function () {
    const draft = syncRepoMappingEditDraftFromForm();
    if (!draft) {
      return;
    }

    if (draft.scm_token || draft.github_token) {
      draft.scm_token = "";
      draft.github_token = "";
      $("#repo_mapping_edit_scm_token").val("");
    } else if (draft.clear_saved_token) {
      draft.clear_saved_token = false;
    } else if (draft.has_saved_token) {
      draft.clear_saved_token = true;
    }

    repoMappingState.editingDraft = { ...draft };
    updateRepoMappingModalTokenControls();
  });

  $("#save_config").off("click").on("click", function () {
    $.ajax({
      url: "/api/config/save",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(collectConfig()),
    })
      .done((data) => {
        const savedTokenSpaces = new Set((data.repo_mapping_token_spaces || []).map((item) => String(item || "").trim().toUpperCase()));
        const refreshedItems = currentRepoMappings().map((item) => ({
          ...item,
          scm_token: "",
          github_token: "",
          has_saved_token: savedTokenSpaces.has(item.space_key),
          clear_saved_token: false,
        }));
        renderRepoMappings(refreshedItems);
        $("#jira_api_token").val("");
        setSavedSecretState("#jira_api_token", Boolean(data.jira_api_token_saved), "현재 저장한 토큰이 있다.", "Jira API Token");
        setGithubTokenHelp(savedTokenSpaces.size > 0);
        clearResultActions("#config_result_actions");
        setResult("#config_result", data);
      })
      .fail((xhr) => {
        clearResultActions("#config_result_actions");
        setResult("#config_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  });

  $("#allow_auto_push").closest("label").contents().last()[0].textContent = " 커밋 후 원격 저장소까지 push";
});

FIELD_LABELS.agent_provider = "Agent Provider";
FIELD_LABELS.claude_model = "Claude Model";
FIELD_LABELS.claude_permission_mode = "Permission Mode";
FIELD_LABELS.enable_plan_review = "실행 전 계획 확인 사용";
VISIBLE_WORKFLOW_PHASES.add("agent_start");
VISIBLE_WORKFLOW_PHASES.add("agent_end");
VISIBLE_WORKFLOW_PHASES.add("agent_timeout");
WORKFLOW_PHASE_LABELS.agent_start = "Agent 시작";
WORKFLOW_PHASE_LABELS.agent_end = "Agent 종료";
WORKFLOW_PHASE_LABELS.agent_timeout = "Agent 시간 초과";

function agentProviderOptions() {
  return window.__AGENT_PROVIDER_OPTIONS__ || {};
}

function currentAgentProvider() {
  return String($("#agent_provider").val() || window.__AGENT_PROVIDER_DEFAULT__ || "codex").trim() || "codex";
}

function currentAgentProviderOption() {
  const provider = currentAgentProvider();
  const options = agentProviderOptions();
  return options[provider] || { provider, label: provider, available: true, default_model: "", default_execution_mode: "" };
}

function agentExecutionModeSummary(provider, value) {
  const normalizedProvider = String(provider || "").trim() || "codex";
  const normalizedValue = String(value || "").trim();
  if (!normalizedValue) {
    return "";
  }
  if (normalizedProvider === "claude") {
    return `permission: ${normalizedValue}`;
  }
  return `reasoning: ${normalizedValue}`;
}

function renderAgentProviderStatus() {
  const option = currentAgentProviderOption();
  const status = $("#agent_provider_status");
  if (!status.length) {
    return;
  }
  const lines = [
    `<strong>${escapeHtml(option.label || "Agent")}</strong>`,
    `<span>${escapeHtml(option.available ? "실행 가능" : "실행기 확인 필요")}</span>`,
  ];
  if (option.launcher) {
    lines.push(`<span>launcher: ${escapeHtml(option.launcher)}</span>`);
  }
  if (option.default_model) {
    lines.push(`<span>기본 모델 ${escapeHtml(option.default_model)}</span>`);
  } else if (String(option.provider || "").trim() === "claude") {
    lines.push("<span>기본 모델 Claude Code 로컬 기본값</span>");
  }
  if (option.default_execution_mode) {
    lines.push(`<span>${escapeHtml(option.execution_mode_label || "Execution Mode")} ${escapeHtml(option.default_execution_mode)}</span>`);
  }
  if (option.error) {
    lines.push(`<span>${escapeHtml(option.error)}</span>`);
  }
  status
    .toggleClass("is-unavailable", option.available === false)
    .html(lines.join(""));
  $("#run_automation").prop("disabled", option.available === false);
}

function syncAgentProviderPanels() {
  const provider = currentAgentProvider();
  $("[data-agent-provider-panel]").each(function () {
    const panelProvider = String($(this).attr("data-agent-provider-panel") || "").trim();
    $(this).prop("hidden", panelProvider !== provider);
  });
  renderAgentProviderStatus();
}

function collectWorkflow() {
  const issue = selectedIssue();
  const detail = issue && jiraState.selectedIssueDetail && jiraState.selectedIssueDetail.issue_key === issue.issue_key
    ? jiraState.selectedIssueDetail
    : null;
  return {
    issue_key: $("#issue_key").val().trim(),
    issue_summary: $("#issue_summary").val().trim(),
    branch_name: $("#branch_name").val().trim(),
    commit_message: $("#commit_message").val().trim(),
    agent_provider: currentAgentProvider(),
    codex_model: $("#codex_model").val().trim(),
    codex_reasoning_effort: $("#codex_reasoning_effort").val().trim(),
    claude_model: $("#claude_model").val().trim(),
    claude_permission_mode: $("#claude_permission_mode").val().trim(),
    work_instruction: $("#work_instruction").val().trim(),
    acceptance_criteria: $("#acceptance_criteria").val().trim(),
    test_command: $("#test_command").val().trim(),
    commit_checklist: $("#commit_checklist").val().trim(),
    git_author_name: $("#git_author_name").val().trim(),
    git_author_email: $("#git_author_email").val().trim(),
    issue_status: detail ? (detail.status || "") : "",
    issue_type: detail ? (detail.issue_type || "") : "",
    issue_priority: detail ? (detail.priority || "") : "",
    issue_assignee: detail ? (detail.assignee || "") : "",
    issue_labels: detail ? ((detail.labels || []).join(", ")) : "",
    issue_description: detail ? (detail.description || "") : "",
    issue_comments_text: detail ? (detail.comments_text || "") : "",
    clarification_questions: workflowState.clarificationQuestions.map((item) => ({ ...item })),
    clarification_answers: { ...workflowState.clarificationAnswers },
    allow_auto_commit: $("#allow_auto_commit").is(":checked"),
    allow_auto_push: $("#allow_auto_push").is(":checked"),
    enable_plan_review: $("#enable_plan_review").is(":checked"),
  };
}

function requestedInfoForFields(fields) {
  const automationMap = {
    agent_provider: { guide_section: "automation", guide_step_id: "automation-agent-provider" },
    branch_name: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    commit_message: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    codex_model: { guide_section: "automation", guide_step_id: "automation-codex-model" },
    codex_reasoning_effort: { guide_section: "automation", guide_step_id: "automation-codex-model" },
    claude_model: { guide_section: "automation", guide_step_id: "automation-claude-model" },
    claude_permission_mode: { guide_section: "automation", guide_step_id: "automation-claude-model" },
    work_instruction: { guide_section: "automation", guide_step_id: "automation-work-instruction" },
    acceptance_criteria: { guide_section: "automation", guide_step_id: "automation-acceptance-criteria" },
    enable_plan_review: { guide_section: "automation", guide_step_id: "automation-plan-review" },
    commit_checklist: { guide_section: "automation", guide_step_id: "automation-commit-checklist" },
    git_author_name: { guide_section: "automation", guide_step_id: "automation-git-author" },
    git_author_email: { guide_section: "automation", guide_step_id: "automation-git-author" },
    issue_key: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    issue_summary: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
  };
  return fields.map((field) => ({
    field,
    label: fieldLabel(field),
    guide_section: automationMap[field] ? automationMap[field].guide_section : "automation",
    guide_step_id: automationMap[field] ? automationMap[field].guide_step_id : "",
  }));
}

function setAutomationResultHint(text) {
  $("#automation_result_hint").text(String(text || "Agent 자동 작업을 실행하면 결과를 여기에서 확인할 수 있다."));
}

function renderAutomationResult(data) {
  const payload = data.result || data.error || data;
  const provider = String(payload.agent_provider || data.agent_provider || "codex").trim() || "codex";
  const providerOption = agentProviderOptions()[provider] || {};
  const providerLabel = payload.resolved_agent_label || providerOption.label || (provider === "claude" ? "Claude Code" : "Codex");
  const modelLabel = payload.resolved_agent_model || payload.resolved_model || payload.requested_agent_model || payload.requested_model || payload.claude_default_model || payload.codex_default_model || "CLI default";
  const executionValue = payload.resolved_agent_execution_mode || payload.resolved_reasoning_effort || payload.requested_agent_execution_mode || payload.requested_reasoning_effort || payload.claude_default_permission_mode || payload.codex_default_reasoning_effort || "";
  const latestEvent = latestWorkflowEvent(data);
  const syntaxReturncode = payload.syntax_check_returncode != null ? payload.syntax_check_returncode : payload.test_returncode;
  const syntaxOutput = payload.syntax_check_output || payload.test_output || "";
  const syntaxElapsed = payload.syntax_check_elapsed_seconds != null ? payload.syntax_check_elapsed_seconds : payload.test_elapsed_seconds;
  const syntaxFiles = payload.syntax_checked_files || [];
  const elapsedSeconds = payload.agent_elapsed_seconds != null ? payload.agent_elapsed_seconds : payload.codex_elapsed_seconds;
  const lastProgress = payload.agent_last_progress_message || payload.codex_last_progress_message || "-";
  const progressCount = payload.agent_progress_event_count != null ? payload.agent_progress_event_count : payload.codex_progress_event_count;
  const syntaxDetail = syntaxFiles.length ? `대상 파일 ${syntaxFiles.length}개` : (payload.test_command || "지정한 검증 명령이 없다.");
  const cards = [
    setSummaryCard("상태", data.status || payload.status || "-", data.message || payload.message || ""),
    setSummaryCard("현재 단계", latestEvent ? (WORKFLOW_PHASE_LABELS[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
    setSummaryCard("Agent", providerLabel, payload.provider_metadata && payload.provider_metadata.execution_mode_label ? payload.provider_metadata.execution_mode_label : ""),
    setSummaryCard("모델", modelLabel, agentExecutionModeSummary(provider, executionValue)),
    setSummaryCard("경과 시간", workflowElapsedLabel(data), elapsedSeconds != null ? `${providerLabel} ${elapsedSeconds}초 / 문법 ${syntaxElapsed == null ? "-" : `${syntaxElapsed}초`}` : ""),
    setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
    setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
    setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxDetail),
    setSummaryCard("최근 진행", lastProgress, progressCount ? `이벤트 ${progressCount}건` : ""),
  ].join("");

  $("#automation_overview").html(cards);
  $("#automation_intent").text(payload.model_intent || "응답 없음");
  $("#automation_implementation").text(payload.implementation_summary || "응답 없음");
  $("#automation_validation").text(payload.validation_summary || "응답 없음");

  const risks = payload.risks || [];
  $("#automation_risks").html(
    risks.length
      ? risks.map((risk) => `<li>${escapeHtml(risk)}</li>`).join("")
      : '<li class="file-list__empty">특이 리스크가 보고되지 않았다.</li>'
  );

  const files = payload.processed_files || [];
  $("#automation_files").html(
    files.length
      ? files.map((file) => `<li>${escapeHtml(file)}</li>`).join("")
      : '<li class="file-list__empty">변경 파일이 없다.</li>'
  );

  $("#automation_diff").text(payload.diff || "diff 없음");
  $("#automation_test_output").text(syntaxOutput || "문법 검사 출력이 없다.");
  $("#automation_log").text(eventLogText(data.events));
  renderAutomationSync(data);
}

$(document).ready(function () {
  $("#agent_provider").on("change", function () {
    syncAgentProviderPanels();
  });
  syncAgentProviderPanels();
});

function agentRunButtonLabel() {
  return "Agent 자동 작업 실행";
}

resetAutomationResultPanel = function () {
  $("#automation_overview").empty();
  $("#automation_intent").text("응답 없음");
  $("#automation_implementation").text("응답 없음");
  $("#automation_validation").text("응답 없음");
  $("#automation_risks").html('<li class="file-list__empty">리스크가 보고되지 않았다.</li>');
  $("#automation_files").html('<li class="file-list__empty">변경 파일이 없다.</li>');
  $("#automation_diff").text("diff 없음");
  $("#automation_test_output").text("검증 출력이 없다.");
  $("#automation_log").text("이벤트 로그가 없다.");
  renderAutomationSync(null);
  setAutomationResultPanelOpen(false);
  setAutomationResultHint("Agent 자동 작업을 실행하면 결과를 여기에 표시한다.");
};

syncAutomationResultPanel = function (data) {
  const payload = (data && (data.result || data.error || data)) || {};
  const status = data && data.status ? String(data.status) : String(payload.status || "");
  const message = String((data && data.message) || payload.message || "").trim();
  let hint = "Agent 자동 작업을 실행하면 결과를 여기에 표시한다.";

  if (status === "queued") {
    hint = "Agent 자동 작업 요청을 접수했다.";
  } else if (status === "running") {
    hint = message || "Agent 자동 작업을 진행 중이다.";
  } else if (status === "completed") {
    hint = message || "Agent 자동 작업을 완료했다.";
  } else if (status === "failed") {
    hint = message || "Agent 자동 작업이 실패했다.";
  } else if (message) {
    hint = message;
  }

  showAutomationResultPanel();
  setAutomationResultHint(hint);
};

scheduleWorkflowPoll = function (runId, button) {
  stopWorkflowPolling();
  workflowState.activeRunId = runId;
  workflowState.pollTimer = window.setTimeout(() => {
    $.getJSON(`/api/workflow/run/${encodeURIComponent(runId)}`)
      .done((data) => {
        const payload = data.result || data.error || {};
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", payload.requested_information || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);

        if (data.status === "completed" || data.status === "failed") {
          stopWorkflowPolling();
          workflowState.activeRunId = null;
          button.prop("disabled", false).text(agentRunButtonLabel());
          return;
        }
        scheduleWorkflowPoll(runId, button);
      })
      .fail((xhr) => {
        stopWorkflowPolling();
        workflowState.activeRunId = null;
        button.prop("disabled", false).text(agentRunButtonLabel());
        const data = xhr.status === 404
          ? {
            ok: false,
            error: "workflow_run_not_found",
            message: "실행 정보를 찾을 수 없다.",
          }
          : {
            ok: false,
            error: "workflow_run_status_failed",
            message: xhr.responseJSON && xhr.responseJSON.message ? xhr.responseJSON.message : "실행 상태를 불러오지 못했다.",
          };
        setResult("#workflow_result", data);
        renderCallout("#workflow_result_actions", (data && data.requested_information) || []);
        renderAutomationResult(data);
        syncAutomationResultPanel(data);
      });
  }, 1500);
};

executeWorkflowRunWithClarification = function (button, payload) {
  button.prop("disabled", true).text("실행 중..");
  clearWorkflowClarification();
  showAutomationResultPanel(true);
  setAutomationResultHint("Agent 자동 작업 요청을 접수했다.");
  setResult("#workflow_result", { ok: false, status: "queued", message: "Agent 자동 작업을 접수했다." });
  $("#automation_log").text("실행 요청을 전송했다.");

  $.ajax({
    url: "/api/workflow/run",
    method: "POST",
    contentType: "application/json",
    data: JSON.stringify(payload),
  })
    .done((data) => {
      setResult("#workflow_result", data);
      renderCallout("#workflow_result_actions", data.requested_information || []);
      renderAutomationResult(data);
      syncAutomationResultPanel(data);
      if (data.run_id) {
        scheduleWorkflowPoll(data.run_id, button);
      } else {
        button.prop("disabled", false).text(agentRunButtonLabel());
      }
    })
    .fail((xhr) => {
      const data = xhr.responseJSON || { ok: false, error: xhr.responseText };
      setResult("#workflow_result", data);
      renderCallout("#workflow_result_actions", data.requested_information || []);
      renderAutomationResult(data);
      syncAutomationResultPanel(data);
      button.prop("disabled", false).text(agentRunButtonLabel());
    });
};

requestWorkflowClarification = function (button, payload) {
  button.prop("disabled", true).text("사전 확인 중..");
  clearResultActions("#workflow_result_actions");

  $.ajax({
    url: "/api/workflow/clarify",
    method: "POST",
    contentType: "application/json",
    data: JSON.stringify(payload),
  })
    .done((data) => {
      setResult("#workflow_result", data);
      if (data.status === "needs_input") {
        renderWorkflowClarification(data);
        button.prop("disabled", false).text(agentRunButtonLabel());
        return;
      }

      clearWorkflowClarification();
      executeWorkflowRunWithClarification(button, payload);
    })
    .fail((xhr) => {
      const data = xhr.responseJSON || { ok: false, error: xhr.responseText };
      clearWorkflowClarification();
      setResult("#workflow_result", data);
      renderCallout("#workflow_result_actions", data.requested_information || []);
      button.prop("disabled", false).text(agentRunButtonLabel());
    });
};

$(document).ready(function () {
  $("#run_automation").off("click").on("click", function () {
    const button = $(this);
    syncWorkflowClarificationAnswers();
    const payload = collectWorkflow();
    const missingFields = workflowRequiredFields(payload);

    stopWorkflowPolling();
    resetAutomationResult();
    hideAutomationResultPanel();
    clearResultActions("#workflow_result_actions");
    if (missingFields.length) {
      const requestedInformation = requestedInfoForFields(missingFields);
      const data = {
        ok: false,
        error: "workflow_fields_missing",
        fields: missingFields,
        requested_information: requestedInformation,
        message: "필수 입력값이 비어 있어 Agent 실행을 시작하지 않았다.",
      };
      setResult("#workflow_result", data);
      renderCallout("#workflow_result_actions", requestedInformation);
      renderAutomationResult(data);
      focusFields([missingFields[0]]);
      return;
    }

    if (workflowState.clarificationQuestions.length) {
      const missingClarifications = missingClarificationItems();
      if (missingClarifications.length) {
        setResult("#workflow_result", {
          ok: false,
          error: "clarification_answers_missing",
          fields: missingClarifications.map((item) => item.field),
          message: "추가 확인 질문에 대한 답변을 모두 입력해 달라.",
        });
        const firstField = missingClarifications[0].field;
        const firstInput = $(`[data-clarification-answer="${firstField}"]`);
        if (firstInput.length) {
          firstInput.trigger("focus");
        }
        return;
      }
    }

    requestWorkflowClarification(button, payload);
  });
});
