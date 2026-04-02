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
};

const workflowState = {
  pollTimer: null,
  activeRunId: null,
  resultPanelOpen: true,
  clarificationQuestions: [],
  clarificationAnswers: {},
  lastJiraCommentSync: null,
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
    .filter((parts) => parts.length === 5 && parts.every(Boolean))
    .map((parts) => ({
      space_key: parts[0],
      repo_owner: parts[1],
      repo_name: parts[2],
      base_branch: parts[3],
      local_repo_path: parts[4],
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

function currentRepoMappings() {
  return $("#repo_mapping_list .repo-mapping-item").map(function () {
    const row = $(this);
    return {
      space_key: row.attr("data-space-key") || "",
      repo_owner: row.attr("data-repo-owner") || "",
      repo_name: row.attr("data-repo-name") || "",
      base_branch: row.attr("data-base-branch") || "",
      local_repo_path: row.attr("data-local-repo-path") || "",
    };
  }).get();
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
}

function clearRepoMappingInputs() {
  $("#mapping_space_key").val("");
  $("#mapping_repo_owner").val("");
  $("#mapping_repo_name").val("");
  $("#mapping_base_branch").val("main");
  $("#mapping_local_repo_path").val("");
}

function readRepoMappingInputs() {
  return {
    space_key: $("#mapping_space_key").val().trim().toUpperCase(),
    repo_owner: $("#mapping_repo_owner").val().trim(),
    repo_name: $("#mapping_repo_name").val().trim(),
    base_branch: $("#mapping_base_branch").val().trim() || "main",
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
  $(id).text(JSON.stringify(payload, null, 2));
}

function clearResultActions(targetId) {
  $(targetId).empty();
}

function fillConfig(data) {
  const repoMappings = parseRepoMappingsText(data.repo_mappings || "");
  renderRepoMappings(repoMappings);
  Object.keys(data).forEach((key) => {
    if (key === "repo_mappings") {
      return;
    }
    const el = $("#" + key);
    if (el.length) {
      el.val(data[key]);
    }
  });
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
      $("body").addClass("modal-open");
      $("#setup_guide_modal").addClass("is-open").attr("aria-hidden", "false");
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
  $("body").removeClass("modal-open");
  $("#setup_guide_modal").removeClass("is-open").attr("aria-hidden", "true");
}

function focusFields(fieldIds) {
  const ids = fieldIds || [];
  if (!ids.length) {
    return;
  }

  closeGuide();

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

function setupIssueTable(data) {
  const rows = (data.issues || [])
    .map((issue, idx) => {
      const checked = idx === 0 ? 'checked="checked"' : "";
      const safeKey = escapeHtml(issue.key || "");
      const safeSummary = escapeHtml(issue.summary || "");
      const safeStatus = escapeHtml(issue.status || "");
      return `
        <tr>
          <td>${safeKey}</td>
          <td>${safeSummary}</td>
          <td>${safeStatus}</td>
          <td>
            <input
              type="radio"
              name="selected_issue"
              ${checked}
              data-key="${safeKey}"
              data-summary="${safeSummary}"
            >
          </td>
        </tr>
      `;
    })
    .join("");

  $("#issue_table").html(rows);
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
  $("#jira_issue_meta").empty();
  $("#jira_issue_description").text(message || "이슈를 선택하면 상세 설명이 표시됩니다.");
  $("#jira_issue_comments").text(message || "이슈를 선택하면 최근 코멘트가 표시됩니다.");
}

function renderIssueDetail(detail) {
  const metaItems = [
    detail.issue_key || "",
    detail.status ? `상태 ${detail.status}` : "",
    detail.issue_type ? `유형 ${detail.issue_type}` : "",
    detail.priority ? `우선순위 ${detail.priority}` : "",
    detail.assignee ? `담당 ${detail.assignee}` : "",
  ].filter(Boolean);

  const labels = detail.labels || [];
  $("#jira_issue_meta").html(
    metaItems.concat(labels.map((label) => `라벨 ${label}`))
      .map((item) => `<span class="field-pill">${escapeHtml(item)}</span>`)
      .join("")
  );
  $("#jira_issue_description").text(detail.description || "Jira 설명이 비어 있습니다.");
  $("#jira_issue_comments").text(detail.comments_text || "최근 코멘트가 없습니다.");
}

function loadIssueDetail(issueKey) {
  const key = String(issueKey || "").trim();
  if (!key) {
    resetIssueDetail();
    return;
  }

  if (jiraState.issueDetailRequest && typeof jiraState.issueDetailRequest.abort === "function") {
    jiraState.issueDetailRequest.abort();
  }

  jiraState.pendingIssueKey = key;
  $("#jira_issue_meta").empty();
  $("#jira_issue_description").text(`${key} 상세를 불러오는 중입니다...`);
  $("#jira_issue_comments").text(`${key} 코멘트를 불러오는 중입니다...`);

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
      $("#jira_issue_meta").empty();
      $("#jira_issue_description").text("이슈 상세를 불러오지 못했습니다.");
      $("#jira_issue_comments").text((xhr.responseJSON && xhr.responseJSON.error) || xhr.responseText || "오류");
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
      <span>${escapeHtml(detail || "")}</span>
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
  $("#test_command").attr("placeholder", "자동 실행하지 않습니다. 필요하면 참고용 명령만 적어 두세요.");
  $("#mapping_space_key").attr("placeholder", "예: GCPPLDCAD");
  $("#mapping_local_repo_path").attr("placeholder", "로컬 저장소 경로");
  $("#add_repo_mapping").text("연결 추가");
  $(".repo-mapping-help").first().text("Jira 공간명과 연결할 GitHub 레포를 나눠서 입력합니다. 공간명을 먼저 적고, 아래 저장소 정보를 입력한 뒤 추가하세요.");
  $("#repo_mappings").closest("label").contents().first()[0].textContent = "공간별 저장소 연결";
  $("#test_command").closest("label").contents().first()[0].textContent = "참고용 로컬 테스트 명령";
  $("#allow_auto_commit").closest("label").contents().last()[0].textContent = " 로컬 테스트 없이 자동 커밋 허용";
  if (!$(".repo-mapping-section-title").length) {
    $("<div>", { class: "repo-mapping-section-title", text: "1. Jira 공간명" }).insertBefore("#mapping_space_key");
    $("<div>", { class: "repo-mapping-section-title", text: "2. 연결할 저장소" }).insertBefore("#mapping_repo_owner");
  }

  FIELD_LABELS.local_repo_path = "기본 로컬 레포 경로";
  $("#test_command").attr("placeholder", "자동 실행하지 않습니다. 필요하면 참고용 명령만 적어 두세요.");
  $("#mapping_space_key").attr("placeholder", "예: GCPPLDCAD");
  $("#mapping_local_repo_path").attr("placeholder", "로컬 레포 경로");
  $("#add_repo_mapping").text("연결 추가");
  $(".repo-mapping-help").first().text("여러 Jira 공간을 각각 다른 저장소에 연결할 때만 펼쳐서 입력합니다. 각 공간 연결에는 로컬 레포 경로도 함께 포함됩니다.");
  const mappingLabel = $("#repo_mappings").closest("label");
  const localRepoLabel = $("#local_repo_path").closest("label");
  if (localRepoLabel.length) {
    localRepoLabel.contents().first()[0].textContent = "기본 로컬 레포 경로";
  }
  $("#test_command").closest("label").contents().first()[0].textContent = "참고용 로컬 테스트 명령";
  $("#allow_auto_commit").closest("label").contents().last()[0].textContent = " 로컬 테스트 없이 자동 커밋 허용";
  $("#jira_issue_comments").closest(".detail-card").find("h3").text("최근 코멘트");
  $("#jira_issue_description").closest(".detail-card").find("h3").text("선택 이슈 상세");
  $("#automation_test_output").closest(".detail-card").find("h3").text("문법 검사 출력");
  const sectionTitles = $(".repo-mapping-section-title");
  if (sectionTitles.length >= 2) {
    $(sectionTitles[0]).text("1. Jira 공간명");
    $(sectionTitles[1]).text("2. 연결할 저장소");
  }

  $("#open_setup_guide").on("click", function () {
    openGuide("jira", "jira-base-url");
  });

  $("#close_setup_guide").on("click", function () {
    closeGuide();
  });

  $("#toggle_automation_result").on("click", function () {
    setAutomationResultPanelOpen(!workflowState.resultPanelOpen);
  });

  $(document).on("click", "[data-close-guide='true']", function () {
    closeGuide();
  });

  $(document).on("click", ".js-open-guide", function () {
    openGuide($(this).attr("data-guide-section"), $(this).attr("data-guide-step-id"));
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
    if (event.key === "Escape" && $("#setup_guide_modal").hasClass("is-open")) {
      closeGuide();
    }
  });

  $(document).on("change", "input[name='selected_issue']", function () {
    const issue = selectedIssue();
    if (issue) {
      fillWorkflow(issue);
      loadIssueDetail(issue.issue_key);
    }
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
