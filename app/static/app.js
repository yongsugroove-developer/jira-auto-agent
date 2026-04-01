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
};

const guideState = {
  guide: null,
  guidePromise: null,
  activeSectionId: null,
  activeStepId: null,
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

function clearResultActions() {
  $("#config_result_actions").empty();
}

function fillConfig(data) {
  Object.keys(data).forEach((key) => {
    const el = $("#" + key);
    if (el.length) {
      el.val(data[key]);
    }
  });
}

function selectedIssue() {
  const checked = $("input[name='selected_issue']:checked");
  if (!checked.length) {
    return null;
  }
  return {
    issue_key: checked.data("key"),
    issue_summary: checked.data("summary"),
  };
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
      const node = firstInput.get(0);
      node.scrollIntoView({
        behavior: prefersReducedMotion() ? "auto" : "smooth",
        block: "center",
      });
      firstInput.trigger("focus");
    }
  }, prefersReducedMotion() ? 0 : 120);
}

function renderValidationActions(data) {
  clearResultActions();
  if (data.valid || !data.requested_information || !data.requested_information.length) {
    return;
  }

  const firstMissing = data.requested_information[0];
  const shortcuts = data.requested_information
    .map((item) => {
      return `
        <button
          type="button"
          class="pill-button js-open-guide"
          data-guide-section="${escapeHtml(item.guide_section || "")}"
          data-guide-step-id="${escapeHtml(item.guide_step_id || "")}"
        >
          ${escapeHtml(item.label || item.field)}
        </button>
      `;
    })
    .join("");

  $("#config_result_actions").html(`
    <div class="result-callout">
      <div>
        <strong>누락된 항목을 가이드에서 바로 찾을 수 있습니다.</strong>
        <p>첫 번째 누락 항목부터 단계별 위치 설명과 예시 값을 확인하세요.</p>
      </div>
      <div class="result-callout__actions">
        <button
          type="button"
          class="secondary-button js-open-guide"
          data-guide-section="${escapeHtml(firstMissing.guide_section || "")}"
          data-guide-step-id="${escapeHtml(firstMissing.guide_step_id || "")}"
        >
          누락된 항목 안내 열기
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
}

$(document).ready(function () {
  getSetupGuide();

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

  $("#load_config").on("click", function () {
    $.getJSON("/api/config")
      .done((data) => {
        fillConfig(data);
        clearResultActions();
        setResult("#config_result", { ok: true, message: "저장된 설정을 불러왔습니다." });
      })
      .fail((xhr) => {
        clearResultActions();
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
        renderValidationActions(data);
      })
      .fail((xhr) => {
        clearResultActions();
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
        clearResultActions();
        setResult("#config_result", data);
      })
      .fail((xhr) => {
        clearResultActions();
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
      .done((data) => setResult("#workflow_result", data))
      .fail((xhr) => setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText }));
  });

  $("#prepare_workflow").on("click", function () {
    const issue = selectedIssue();
    if (!issue) {
      setResult("#workflow_result", { ok: false, error: "이슈를 먼저 선택해 주세요." });
      return;
    }
    $.ajax({
      url: "/api/workflow/prepare",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(issue),
    })
      .done((data) => setResult("#workflow_result", data))
      .fail((xhr) => setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText }));
  });
});
