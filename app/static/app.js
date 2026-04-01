const FIELD_LABELS = {
  jira_base_url: "Jira Base URL",
  jira_email: "Jira Email",
  jira_api_token: "Jira API Token",
  jira_jql: "JQL",
  github_owner: "GitHub Owner",
  github_repo: "GitHub Repo",
  github_base_branch: "Base Branch",
  github_token: "GitHub Token",
  local_repo_path: "Local Repo Path",
  branch_name: "Branch Name",
  commit_message: "Commit Message",
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

const workflowState = {
  pollTimer: null,
  activeRunId: null,
};

function collectConfig() {
  return {
    jira_base_url: $("#jira_base_url").val().trim(),
    jira_email: $("#jira_email").val().trim(),
    jira_api_token: $("#jira_api_token").val().trim(),
    jira_jql: $("#jira_jql").val().trim(),
    github_owner: $("#github_owner").val().trim(),
    github_repo: $("#github_repo").val().trim(),
    github_base_branch: $("#github_base_branch").val().trim(),
    github_token: $("#github_token").val().trim(),
    local_repo_path: $("#local_repo_path").val().trim(),
  };
}

function collectWorkflow() {
  return {
    issue_key: $("#issue_key").val().trim(),
    issue_summary: $("#issue_summary").val().trim(),
    branch_name: $("#branch_name").val().trim(),
    commit_message: $("#commit_message").val().trim(),
    work_instruction: $("#work_instruction").val().trim(),
    acceptance_criteria: $("#acceptance_criteria").val().trim(),
    test_command: $("#test_command").val().trim(),
    commit_checklist: $("#commit_checklist").val().trim(),
    git_author_name: $("#git_author_name").val().trim(),
    git_author_email: $("#git_author_email").val().trim(),
    allow_auto_commit: $("#allow_auto_commit").is(":checked"),
  };
}

function workflowRequiredFields(payload) {
  return ["issue_key", "issue_summary", "branch_name", "commit_message", "work_instruction", "test_command"]
    .filter((field) => !String(payload[field] || "").trim());
}

function requestedInfoForFields(fields) {
  const automationMap = {
    branch_name: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    commit_message: { guide_section: "automation", guide_step_id: "automation-branch-commit" },
    work_instruction: { guide_section: "automation", guide_step_id: "automation-work-instruction" },
    acceptance_criteria: { guide_section: "automation", guide_step_id: "automation-acceptance-criteria" },
    test_command: { guide_section: "automation", guide_step_id: "automation-test-command" },
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
  Object.keys(data).forEach((key) => {
    const el = $("#" + key);
    if (el.length) {
      el.val(data[key]);
    }
  });
}

function fillWorkflow(data) {
  Object.keys(data).forEach((key) => {
    const el = $("#" + key);
    if (el.length) {
      el.val(data[key]);
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
  }
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
  const items = events || [];
  if (!items.length) {
    return "실행 로그 없음";
  }
  return items
    .map((event) => `[${event.timestamp}] ${event.phase}: ${event.message}`)
    .join("\n");
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
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }, 1500);
}

function renderAutomationResult(data) {
  const payload = data.result || data.error || data;
  const cards = [
    setSummaryCard("상태", data.status || payload.status || "-", data.message || payload.message || ""),
    setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치: ${payload.current_branch}` : ""),
    setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
    setSummaryCard("테스트", payload.test_returncode == null ? "-" : String(payload.test_returncode), payload.test_command || ""),
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
  $("#automation_log").text(payload.execution_log_tail || eventLogText(data.events) || "실행 로그 없음");
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

function withButtonBusy(button, callback) {
  const originalText = button.text();
  button.prop("disabled", true).text("실행 중...");
  const done = () => button.prop("disabled", false).text(originalText);
  callback(done);
}

$(document).ready(function () {
  getSetupGuide();
  resetAutomationResult();

  $("#open_setup_guide").on("click", function () {
    openGuide("jira", "jira-base-url");
  });

  $("#close_setup_guide").on("click", function () {
    closeGuide();
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
    }
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
      data: JSON.stringify({ mock_mode: $("#mock_mode").is(":checked") }),
    })
      .done((data) => {
        setupIssueTable(data);
        setResult("#backlog_result", data);
      })
      .fail((xhr) => {
        $("#issue_table").empty();
        setResult("#backlog_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  });

  $("#check_repo").on("click", function () {
    $.ajax({
      url: "/api/github/check",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({}),
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
        button.prop("disabled", false).text("Codex 자동 작업 실행");
      });
  });
});
