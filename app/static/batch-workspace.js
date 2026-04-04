(function ($) {
  const batchWorkspaceState = {
    previewTimer: null,
    pollTimer: null,
    preview: null,
    recentBatches: [],
    activeBatch: null,
    activeBatchId: null,
    activeDetailTab: "overview",
    clarificationDrafts: {},
    failedOnly: false,
  };

  const STORAGE_KEYS = {
    activeBatchId: "jira-auto-agent.active-batch-id",
  };

  const DETAIL_TABS = [
    { id: "overview", label: "실행 개요" },
    { id: "summary", label: "결과 요약" },
    { id: "clarification", label: "질문과 코멘트" },
    { id: "artifacts", label: "산출물" },
    { id: "logs", label: "로그" },
  ];

  const FLOW_STEPS = [
    { id: "queued", label: "접수" },
    { id: "prepare", label: "준비" },
    { id: "execute", label: "실행" },
    { id: "review", label: "검토" },
    { id: "done", label: "완료" },
  ];

  function batchRunStorageKey(batchId) {
    return `jira-auto-agent.active-run.${String(batchId || "").trim()}`;
  }

  function batchDetailStorageKey(batchId) {
    return `jira-auto-agent.active-detail.${String(batchId || "").trim()}`;
  }

  function clarificationDraftKey(batchId, runId) {
    return `${String(batchId || "").trim()}:${String(runId || "").trim()}`;
  }

  function safeStorageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function safeStorageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      return;
    }
  }

  function selectedIssues() {
    return $("input[name='selected_issues']:checked").map(function () {
      return {
        issue_key: String($(this).attr("data-key") || "").trim(),
        issue_summary: String($(this).attr("data-summary") || "").trim(),
      };
    }).get();
  }

  function primarySelectedIssue() {
    const issues = selectedIssues();
    if (issues.length) {
      const expandedIssueKey = typeof jiraState !== "undefined"
        ? String(jiraState.expandedIssueKey || "").trim()
        : "";
      if (expandedIssueKey) {
        const expandedIssue = issues.find((issue) => issue.issue_key === expandedIssueKey);
        if (expandedIssue) {
          return expandedIssue;
        }
      }
      return issues[0];
    }

    const issueKey = String($("#issue_key").val() || "").trim();
    const issueSummary = String($("#issue_summary").val() || "").trim();
    if (!issueKey || !issueSummary) {
      return null;
    }
    return { issue_key: issueKey, issue_summary: issueSummary };
  }

  function workflowCommonPayload() {
    return {
      issues: selectedIssues(),
      codex_model: String($("#codex_model").val() || "").trim(),
      codex_reasoning_effort: String($("#codex_reasoning_effort").val() || "").trim(),
      work_instruction: String($("#work_instruction").val() || "").trim(),
      acceptance_criteria: String($("#acceptance_criteria").val() || "").trim(),
      test_command: String($("#test_command").val() || "").trim(),
      commit_checklist: String($("#commit_checklist").val() || "").trim(),
      git_author_name: String($("#git_author_name").val() || "").trim(),
      git_author_email: String($("#git_author_email").val() || "").trim(),
      allow_auto_commit: $("#allow_auto_commit").is(":checked"),
      allow_auto_push: $("#allow_auto_push").is(":checked"),
    };
  }

  function syncPrimaryIssueFields() {
    const issue = primarySelectedIssue();
    if (!issue) {
      $("#issue_key").val("");
      $("#issue_summary").val("");
      $("#branch_name").val("");
      $("#commit_message").val("");
      return null;
    }

    $("#issue_key").val(issue.issue_key);
    $("#issue_summary").val(issue.issue_summary);
    $("#branch_name").val(`feature/${issue.issue_key.toUpperCase()}-${String(issue.issue_summary).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "task"}`);
    $("#commit_message").val(`${issue.issue_key.toUpperCase()}: ${issue.issue_summary}`);
    return issue;
  }

  function renderSelectionSummary() {
    const issues = selectedIssues();
    const issueKeys = $("#selected_issue_keys");
    $("#selected_issue_count").text(`선택한 이슈 ${issues.length}건`);
    if (!issueKeys.length) {
      return;
    }
    if (!issues.length) {
      issueKeys.text("").attr("hidden", true);
      return;
    }
    issueKeys
      .text(issues.map((issue) => `${issue.issue_key} ${issue.issue_summary}`).join(" / "))
      .attr("hidden", false);
  }

  function setBatchPreviewEmpty(message) {
    $("#workflow_batch_preview_count").text("0건");
    $("#workflow_batch_preview_list").html(`<p class="batch-preview-empty">${escapeHtml(message)}</p>`);
    batchWorkspaceState.preview = null;
  }

  function renderBatchPreview(data) {
    const items = (data && data.issues) || [];
    batchWorkspaceState.preview = data || null;
    $("#workflow_batch_preview_count").text(`${items.length}건`);
    if (!items.length) {
      setBatchPreviewEmpty("이슈를 선택하면 미리보기를 표시한다.");
      return;
    }

    const cards = items.map((item) => `
      <article class="batch-preview-item">
        <div class="batch-preview-item__header">
          <div class="batch-preview-item__title">
            <strong>${escapeHtml(item.issue_key)}</strong>
            <span>${escapeHtml(item.issue_summary)}</span>
          </div>
          <div class="batch-preview-item__pills">
            <span class="queue-badge ${item.queue_mode === "serial" ? "is-serial" : "is-parallel"}">${escapeHtml(item.queue_mode === "serial" ? "직렬 처리" : "병렬 처리")}</span>
            <span class="field-pill">${escapeHtml(item.resolved_space_key || "SPACE")}</span>
          </div>
        </div>
        <div class="batch-preview-item__meta">
          <div>저장소 ${escapeHtml(item.repo_ref || `${item.repo_owner}/${item.repo_name}`)}</div>
          <div>Provider ${escapeHtml(item.repo_provider || "-")}</div>
          <div>기준 브랜치 ${escapeHtml(item.base_branch || "-")}</div>
          <div>로컬 경로 ${escapeHtml(item.local_repo_path || "-")}</div>
          <div>작업 브랜치 ${escapeHtml(item.branch_name || "-")}</div>
          <div>커밋 메시지 ${escapeHtml(item.commit_message || "-")}</div>
          <div>큐 그룹 ${escapeHtml(item.queue_key || "-")} / 같은 경로 ${escapeHtml(String(item.queue_group_size || 1))}건</div>
        </div>
      </article>
    `).join("");
    $("#workflow_batch_preview_list").html(cards);
  }

  function requestBatchPreview() {
    const payload = workflowCommonPayload();
    if (!payload.issues.length) {
      setBatchPreviewEmpty("이슈를 선택하면 미리보기를 표시한다.");
      return;
    }

    $.ajax({
      url: "/api/workflow/batch/preview",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ issues: payload.issues }),
    })
      .done((data) => {
        renderBatchPreview(data);
        setResult("#workflow_result", { ok: true, message: `배치 미리보기 ${data.selected_issue_count || 0}건을 갱신했습니다.` });
      })
      .fail((xhr) => {
        setBatchPreviewEmpty("미리보기를 불러오지 못했다.");
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }

  function scheduleBatchPreview() {
    if (batchWorkspaceState.previewTimer) {
      window.clearTimeout(batchWorkspaceState.previewTimer);
      batchWorkspaceState.previewTimer = null;
    }
    batchWorkspaceState.previewTimer = window.setTimeout(requestBatchPreview, 200);
  }

  function renderIssueTable(data) {
    const issues = (data && data.issues) || [];
    const rows = issues.map((issue) => {
      if (typeof renderIssueAccordionItem === "function") {
        return renderIssueAccordionItem(issue, {
          inputType: "checkbox",
          inputName: "selected_issues",
        });
      }
      return "";
    }).join("");
    $("#issue_table").html(rows || '<p class="batch-preview-empty">조회된 이슈가 없습니다.</p>');
    if (typeof syncIssueAccordionState === "function") {
      syncIssueAccordionState();
    }
    syncPrimaryIssueFields();
    renderSelectionSummary();
    const issue = primarySelectedIssue();
    if (issue && typeof loadIssueDetail === "function") {
      loadIssueDetail(issue.issue_key);
    } else if (typeof resetIssueDetail === "function") {
      resetIssueDetail();
    }
    scheduleBatchPreview();
  }

  function formatTimestamp(value) {
    const text = String(value || "").trim();
    if (!text) {
      return "-";
    }
    const time = Date.parse(text);
    if (Number.isNaN(time)) {
      return text;
    }
    return new Date(time).toLocaleString("ko-KR", { hour12: false });
  }

  function statusBadge(status) {
    const normalized = String(status || "").trim() || "idle";
    const labels = {
      queued: "대기",
      running: "실행",
      completed: "완료",
      failed: "실패",
      needs_input: "추가 확인",
      partially_completed: "부분 완료",
      idle: "대기",
      finished: "종료",
    };
    return `<span class="status-badge is-${escapeHtml(normalized)}">${escapeHtml(labels[normalized] || normalized)}</span>`;
  }

  function queueMetaBadge(run) {
    const state = String(run.queue_state || "").trim();
    if (!state || state === "idle") {
      return "";
    }
    const labels = {
      queued: run.queue_position ? `큐 ${run.queue_position}` : "큐 대기",
      running: "실행 중",
      finished: "실행 완료",
    };
    return `<span class="field-pill">${escapeHtml(labels[state] || state)}</span>`;
  }

  function showWorkStatusSection(message) {
    $("#work_status_section").prop("hidden", false);
    if (message) {
      $("#work_status_hint").text(String(message));
    }
  }

  function clarificationFocusState() {
    const active = document.activeElement;
    if (!active) {
      return null;
    }
    const field = String($(active).attr("data-batch-clarification-answer") || "").trim();
    if (!field) {
      return null;
    }
    return {
      field,
      selectionStart: typeof active.selectionStart === "number" ? active.selectionStart : null,
      selectionEnd: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
      scrollTop: typeof active.scrollTop === "number" ? active.scrollTop : 0,
    };
  }

  function clarificationEditorFocused() {
    return Boolean(clarificationFocusState());
  }

  function currentClarificationDrafts(batchId, runId) {
    return batchWorkspaceState.clarificationDrafts[clarificationDraftKey(batchId, runId)] || {};
  }

  function setClarificationDraftValue(batchId, runId, field, value) {
    const key = clarificationDraftKey(batchId, runId);
    const drafts = { ...currentClarificationDrafts(batchId, runId) };
    drafts[field] = value;
    batchWorkspaceState.clarificationDrafts[key] = drafts;
  }

  function clearClarificationDrafts(batchId, runId) {
    delete batchWorkspaceState.clarificationDrafts[clarificationDraftKey(batchId, runId)];
  }

  function restoreClarificationFocus(focusState) {
    if (!focusState) {
      return;
    }
    const target = $("#batch_run_clarification_questions [data-batch-clarification-answer]").filter(function () {
      return String($(this).attr("data-batch-clarification-answer") || "").trim() === focusState.field;
    }).get(0);
    if (!target) {
      return;
    }
    target.focus();
    if (focusState.selectionStart != null && focusState.selectionEnd != null && typeof target.setSelectionRange === "function") {
      target.setSelectionRange(focusState.selectionStart, focusState.selectionEnd);
    }
    if (typeof target.scrollTop === "number") {
      target.scrollTop = focusState.scrollTop || 0;
    }
  }

  function stopBatchPolling() {
    if (batchWorkspaceState.pollTimer) {
      window.clearTimeout(batchWorkspaceState.pollTimer);
      batchWorkspaceState.pollTimer = null;
    }
  }

  function currentBatchShouldPoll(batch) {
    if (!batch) {
      return false;
    }
    const status = String(batch.status || "").trim();
    if (status === "queued" || status === "running") {
      return true;
    }
    const runs = batch.runs || [];
    return runs.some((run) => ["queued", "running"].includes(String(run.status || "").trim()));
  }

  function scheduleBatchPoll(batchId) {
    stopBatchPolling();
    batchWorkspaceState.pollTimer = window.setTimeout(() => {
      if (clarificationEditorFocused()) {
        scheduleBatchPoll(batchId);
        return;
      }
      loadBatch(batchId, { preserveSelection: true, silentListRefresh: false });
    }, 2000);
  }

  function renderBatchSummary(batch) {
    const counts = batch.counts || {};
    const cards = [
      setSummaryCard("배치 ID", String(batch.batch_id || "").slice(0, 10) || "-"),
      setSummaryCard("상태", batch.status || "-"),
      setSummaryCard("전체 이슈", `${counts.total || 0}건`),
      setSummaryCard("진행 중", `${(counts.queued || 0) + (counts.running || 0)}건`),
      setSummaryCard("추가 확인", `${counts.needs_input || 0}건`),
      setSummaryCard("완료", `${counts.completed || 0}건`),
      setSummaryCard("부분 완료", `${counts.partially_completed || 0}건`),
      setSummaryCard("실패", `${counts.failed || 0}건`),
    ].join("");
    $("#batch_summary_cards").html(cards);
  }

  function preferredDetailTab(batch) {
    if (!batch || !batch.batch_id) {
      return DETAIL_TABS[0].id;
    }
    const stored = safeStorageGet(batchDetailStorageKey(batch.batch_id));
    if (stored && DETAIL_TABS.some((item) => item.id === stored)) {
      return stored;
    }
    return DETAIL_TABS[0].id;
  }

  function setActiveDetailTab(batchId, detailTab) {
    const normalized = DETAIL_TABS.some((item) => item.id === detailTab) ? detailTab : DETAIL_TABS[0].id;
    batchWorkspaceState.activeDetailTab = normalized;
    if (batchId) {
      safeStorageSet(batchDetailStorageKey(batchId), normalized);
    }
  }

  function preferredRunId(batch) {
    const stored = safeStorageGet(batchRunStorageKey(batch.batch_id));
    const runs = (batch.runs || []).map((run) => String(run.run_id || ""));
    if (stored && runs.includes(stored)) {
      return stored;
    }
    return String(batch.active_run_id || batch.suggested_active_run_id || (batch.runs[0] && batch.runs[0].run_id) || "");
  }

  function visibleRuns(batch) {
    const runs = batch.runs || [];
    if (!batchWorkspaceState.failedOnly) {
      return runs;
    }
    const failedRuns = runs.filter((run) => ["failed", "partially_completed"].includes(String(run.status || "").trim()));
    return failedRuns.length ? failedRuns : runs;
  }

  function activeFlowRuns(batch) {
    return (batch.runs || []).filter((run) => ["queued", "running", "needs_input"].includes(String(run.status || "").trim()));
  }

  function renderRunTabs(batch, activeRunId) {
    const runs = visibleRuns(batch);
    const tabs = runs.map((run) => {
      const isActive = String(run.run_id) === String(activeRunId);
      const title = String(run.issue_summary || run.tab_label || run.issue_key || run.run_id || "").trim();
      return `
        <button
          type="button"
          class="workspace-tab workspace-tab--run ${isActive ? "is-active" : ""}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
          data-run-id="${escapeHtml(run.run_id)}"
        >
          <span class="workspace-tab__meta">
            <span class="workspace-tab__eyebrow">${escapeHtml(run.issue_key || "Issue")}</span>
            <strong>${escapeHtml(title || run.run_id)}</strong>
          </span>
        </button>
      `;
    }).join("");
    $("#batch_run_tabs").html(tabs || '<p class="batch-list__empty">표시할 실행 탭이 없다.</p>');
  }

  function renderDetailTabs(activeDetailTab) {
    const tabs = DETAIL_TABS.map((item) => {
      const isActive = item.id === activeDetailTab;
      return `
        <button
          type="button"
          class="workspace-tab workspace-tab--detail ${isActive ? "is-active" : ""}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
          data-detail-tab="${escapeHtml(item.id)}"
        >
          <span class="workspace-tab__meta">
            <strong>${escapeHtml(item.label)}</strong>
          </span>
        </button>
      `;
    }).join("");
    $("#batch_detail_tabs").html(tabs);
    DETAIL_TABS.forEach((item) => {
      $(`[data-detail-panel="${item.id}"]`).prop("hidden", item.id !== activeDetailTab);
    });
  }

  function runPayload(run) {
    return run.result || run.error || run;
  }

  function renderRunMeta(run, payload) {
    const items = [
      statusBadge(run.status),
      queueMetaBadge(run),
      run.resolved_space_key ? `<span class="field-pill">${escapeHtml(run.resolved_space_key)}</span>` : "",
      run.local_repo_path ? `<span class="field-pill">${escapeHtml(run.local_repo_path)}</span>` : "",
      payload.branch_name ? `<span class="field-pill">${escapeHtml(payload.branch_name)}</span>` : "",
      payload.commit_message ? `<span class="field-pill">${escapeHtml(payload.commit_message)}</span>` : "",
    ].filter(Boolean).join("");
    $("#batch_run_meta").html(items);
  }

  function flowStatusLabel(run, payload, latestEvent) {
    const status = String(run.status || payload.status || "").trim();
    if (status === "needs_input") {
      return "추가 확인 답변을 기다린다.";
    }
    if (status === "failed" || status === "partially_completed") {
      return run.message || payload.message || "실패 또는 부분 완료 상태다.";
    }
    if (latestEvent && latestEvent.message) {
      return latestEvent.message;
    }
    if (status === "completed") {
      return "배치 작업이 완료됐다.";
    }
    if (status === "running") {
      return "현재 단계를 계속 진행 중이다.";
    }
    if (run.queue_state === "queued") {
      return run.queue_position ? `큐에서 ${run.queue_position}번째 순서를 기다린다.` : "큐 대기 상태다.";
    }
    return run.message || payload.message || "대기 중이다.";
  }

  function resolveFlowState(run, payload) {
    const latestEvent = typeof latestWorkflowEvent === "function" ? latestWorkflowEvent(run) : null;
    const phase = String((latestEvent && latestEvent.phase) || "").trim();
    const status = String(run.status || payload.status || "").trim();
    let activeStepId = "queued";

    if (status === "needs_input") {
      activeStepId = "review";
    } else if (["completed", "failed", "partially_completed"].includes(status)) {
      activeStepId = "done";
    } else if (["syntax_start", "syntax_end", "stage_changes", "stage_ready", "commit_start", "commit_end"].includes(phase)) {
      activeStepId = "review";
    } else if (phase.startsWith("codex") || status === "running") {
      activeStepId = "execute";
    } else if (["branch_prepare", "branch_ready"].includes(phase) || run.queue_state === "running") {
      activeStepId = "prepare";
    }

    const activeIndex = FLOW_STEPS.findIndex((step) => step.id === activeStepId);
    const completedRun = status === "completed";
    const failedRun = status === "failed" || status === "partially_completed";
    const steps = FLOW_STEPS.map((step, index) => {
      let className = "";
      if (completedRun) {
        className = "is-complete";
      } else if (failedRun) {
        if (index < activeIndex) {
          className = "is-complete";
        } else if (index === activeIndex) {
          className = "is-failed";
        }
      } else if (index < activeIndex) {
        className = "is-complete";
      } else if (index === activeIndex) {
        className = "is-active";
      }
      return { ...step, className };
    });

    return {
      activeStepId,
      failedRun,
      message: flowStatusLabel(run, payload, latestEvent),
      steps,
    };
  }

  function renderBatchFlowBoard(batch, activeRunId) {
    const runs = activeFlowRuns(batch);
    if (!runs.length) {
      $("#batch_flow_panel").prop("hidden", true);
      $("#batch_flow_board").empty();
      $("#batch_flow_caption").text("");
      return;
    }
    $("#batch_flow_panel").prop("hidden", false);

    const counts = {
      running: runs.filter((run) => String(run.status || "").trim() === "running").length,
      needsInput: runs.filter((run) => String(run.status || "").trim() === "needs_input").length,
      queued: runs.filter((run) => String(run.status || "").trim() === "queued").length,
    };
    $("#batch_flow_caption").text(
      `실행 ${counts.running}건 / 대기 ${counts.queued}건 / 확인 ${counts.needsInput}건`
    );

    const rows = runs.map((run) => {
      const payload = runPayload(run);
      const flow = resolveFlowState(run, payload);
      const isActive = String(run.run_id) === String(activeRunId);
      const normalizedStatus = String(run.status || "").trim().replace(/_/g, "-") || "idle";
      const isProcessing = ["queued", "running", "needs_input"].includes(String(run.status || "").trim());
      const track = flow.steps.map((step) => `
        <div class="batch-flow-step ${step.className}">
          <span class="batch-flow-step__dot" aria-hidden="true"></span>
          <span class="batch-flow-step__label">${escapeHtml(step.label)}</span>
        </div>
      `).join("");
      const title = String(run.issue_summary || run.tab_label || run.issue_key || run.run_id || "").trim();
      return `
        <article class="batch-flow-row ${isActive ? "is-active" : ""} ${flow.failedRun ? "is-failed" : ""} is-status-${escapeHtml(normalizedStatus)} ${isProcessing ? "is-processing" : ""}" data-flow-state="${escapeHtml(flow.activeStepId)}">
          <div class="batch-flow-row__header">
            <div class="batch-flow-row__title">
              <strong>${escapeHtml(title || run.run_id)}</strong>
              <span>${escapeHtml(run.issue_key || "")}</span>
            </div>
            <div class="batch-flow-row__badges">
              ${statusBadge(run.status)}
              ${queueMetaBadge(run)}
            </div>
          </div>
          <div class="batch-flow-track">${track}</div>
          <p class="batch-flow-row__message">${escapeHtml(flow.message)}</p>
        </article>
      `;
    }).join("");

    $("#batch_flow_board").html(rows);
  }

  function renderRunOverview(run, payload) {
    const latestEvent = typeof latestWorkflowEvent === "function" ? latestWorkflowEvent(run) : null;
    const phaseLabels = typeof WORKFLOW_PHASE_LABELS === "object" ? WORKFLOW_PHASE_LABELS : {};
    const syntaxReturncode = payload.syntax_check_returncode != null ? payload.syntax_check_returncode : payload.test_returncode;
    const syntaxFiles = payload.syntax_checked_files || [];
    const cards = [
      setSummaryCard("상태", run.status || payload.status || "-", run.message || payload.message || ""),
      setSummaryCard("현재 단계", latestEvent ? (phaseLabels[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
      setSummaryCard("경과 시간", typeof workflowElapsedLabel === "function" ? workflowElapsedLabel(run) : "-", payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초` : ""),
      setSummaryCard("모델", payload.resolved_model || payload.requested_model || "-", payload.resolved_reasoning_effort ? `reasoning: ${payload.resolved_reasoning_effort}` : ""),
      setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
      setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
      setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxFiles.length ? `대상 파일 ${syntaxFiles.length}개` : (payload.test_command || "")),
      setSummaryCard("업데이트", formatTimestamp(run.updated_at || run.finished_at || run.started_at || run.created_at)),
    ].join("");
    $("#batch_run_overview").html(cards);
  }

  function renderText(target, value, emptyText) {
    $(target).text(String(value || "").trim() || emptyText);
  }

  function renderList(target, items, emptyText) {
    $(target).html(
      (items || []).length
        ? (items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")
        : `<li class="file-list__empty">${escapeHtml(emptyText)}</li>`
    );
  }

  function renderClarificationSection(run) {
    const clarification = run.clarification || {};
    const requested = clarification.requested_information || [];
    const answers = clarification.answers || {};
    const batchId = batchWorkspaceState.activeBatchId;
    const runId = String(run.run_id || "").trim();
    const draftAnswers = currentClarificationDrafts(batchId, runId);
    const hasAnswers = Object.keys(answers).length > 0;
    const editable = String(run.status || "").trim() === "needs_input" && requested.length > 0;
    const focusState = clarificationFocusState();
    const normalizedStatus = String(run.status || "").trim();

    let stateVariant = "is-idle";
    let stateTitle = "추가 질문 없음";
    let stateMessage = "현재 배치에서 추가 입력이 필요한 질문이 없다.";
    if (editable && hasAnswers) {
      stateVariant = "is-followup";
      stateTitle = "추가 질문 도착";
      stateMessage = "이전에 제출한 답변은 잠금 상태이며, 아래 새 질문에만 추가로 답변할 수 있다.";
    } else if (editable) {
      stateVariant = "is-pending";
      stateTitle = "답변 대기 중";
      stateMessage = "답변을 제출하면 이번 배치에서는 추가 질문이 다시 생기지 않는 한 수정할 수 없다.";
    } else if (hasAnswers) {
      stateVariant = "is-locked";
      stateTitle = "답변 제출 완료";
      stateMessage = ["queued", "running"].includes(normalizedStatus)
        ? "제출한 답변이 현재 배치에 반영되어 다시 진행 중이다. 새로운 질문이 없는 한 수정할 수 없다."
        : "제출한 답변이 현재 배치에 반영됐다. 이번 배치에서는 새로운 질문이 없는 한 수정할 수 없다.";
    }

    $("#batch_run_clarification_state").html(`
      <div class="clarification-state-banner__body ${stateVariant}">
        <strong>${escapeHtml(stateTitle)}</strong>
        <p>${escapeHtml(stateMessage)}</p>
      </div>
    `);

    renderText(
      "#batch_run_clarification_summary",
      clarification.analysis_summary || run.message || "",
      "추가 확인이 필요한 경우 이슈 탭 안에서 질문과 답변을 처리한다."
    );

    if (requested.length) {
      const questionItems = requested.map((item) => {
        const answer = Object.prototype.hasOwnProperty.call(draftAnswers, item.field)
          ? String(draftAnswers[item.field] || "")
          : String(answers[item.field] || "");
        return `
          <${editable ? "label" : "article"} class="clarification-question ${editable ? "" : "clarification-question--locked"}">
            <div class="clarification-question__header">
              <span class="clarification-question__label">${escapeHtml(item.label || item.field)}</span>
              ${editable ? "" : '<span class="clarification-lock-badge">수정 잠금</span>'}
            </div>
            <strong class="clarification-question__prompt">${escapeHtml(item.question || "")}</strong>
            <small class="clarification-question__reason">${escapeHtml(item.why || "")}</small>
            ${editable ? `
              <textarea
                rows="3"
                data-batch-clarification-answer="${escapeHtml(item.field)}"
                placeholder="${escapeHtml(item.placeholder || "답변을 입력하세요.")}"
              >${escapeHtml(answer)}</textarea>
            ` : `
              <div class="clarification-answer-item clarification-answer-item--submitted">
                <strong>제출한 답변</strong>
                <p>${escapeHtml(answer || "답변 없음")}</p>
              </div>
            `}
          </${editable ? "label" : "article"}>
        `;
      }).join("");
      $("#batch_run_clarification_questions").html(questionItems).prop("hidden", false);
    } else {
      $("#batch_run_clarification_questions").empty().prop("hidden", true);
    }

    if (hasAnswers) {
      const answerItems = Object.entries(answers).map(([field, answer]) => `
        <article class="clarification-answer-item">
          <strong>${escapeHtml(field)}</strong>
          <p>${escapeHtml(answer)}</p>
        </article>
      `).join("");
      $("#batch_run_clarification_answers").html(answerItems).prop("hidden", false);
    } else {
      $("#batch_run_clarification_answers").empty().prop("hidden", true);
    }

    $("#batch_run_clarification_actions").prop("hidden", !editable);
    $("#submit_batch_run_answers").data("runId", run.run_id);
    if (editable) {
      restoreClarificationFocus(focusState);
    }
  }

  function renderRunSync(run, payload) {
    const syncData = run.jira_comment_sync || payload.jira_comment_sync || null;
    if (typeof renderJiraCommentSync === "function") {
      renderJiraCommentSync("#batch_run_sync_status_list", "#batch_run_sync_status_card", syncData);
    }
  }

  function renderRunDetail(run, activeDetailTab) {
    const payload = runPayload(run);
    renderDetailTabs(activeDetailTab);
    renderRunMeta(run, payload);
    renderRunOverview(run, payload);
    renderText("#batch_run_intent", payload.model_intent, "실행 후 표시한다.");
    renderText("#batch_run_implementation", payload.implementation_summary, "실행 후 표시한다.");
    renderText("#batch_run_validation", payload.validation_summary, "실행 후 표시한다.");
    renderList("#batch_run_risks", payload.risks || [], "특이 리스크가 보고되지 않았다.");
    renderClarificationSection(run);
    renderRunSync(run, payload);
    renderList("#batch_run_files", payload.processed_files || [], "변경 파일이 없다.");
    renderText("#batch_run_diff", payload.diff, "diff 없음");
    renderText("#batch_run_test_output", payload.syntax_check_output || payload.test_output, "문법 검사 출력이 없다.");
    renderText("#batch_run_log", typeof eventLogText === "function" ? eventLogText(run.events) : "실행 로그 없음", "실행 로그 없음");
  }

  function setActiveRun(batchId, runId) {
    batchWorkspaceState.activeBatchId = batchId;
    safeStorageSet(STORAGE_KEYS.activeBatchId, batchId);
    safeStorageSet(batchRunStorageKey(batchId), runId);
  }

  function renderActiveBatch(batch, options) {
    const preserveSelection = Boolean(options && options.preserveSelection);
    batchWorkspaceState.activeBatch = batch;
    batchWorkspaceState.activeBatchId = batch.batch_id;
    safeStorageSet(STORAGE_KEYS.activeBatchId, batch.batch_id);
    renderBatchSummary(batch);
    $("#work_status_empty").prop("hidden", true);
    $("#work_status_content").prop("hidden", false);

    const runs = visibleRuns(batch);
    const activeRunId = preserveSelection
      ? preferredRunId(batch)
      : (preferredRunId(batch) || (runs[0] && runs[0].run_id));
    const activeRun = runs.find((run) => String(run.run_id) === String(activeRunId)) || runs[0] || null;
    const activeDetailTab = preferredDetailTab(batch);

    if (!activeRun) {
      $("#batch_run_tabs").html('<p class="batch-list__empty">표시할 실행 탭이 없다.</p>');
      $("#batch_detail_tabs").empty();
      $("#batch_run_meta").empty();
      $("#batch_flow_panel").prop("hidden", true);
      $("#batch_flow_board").empty();
      $("#batch_flow_caption").text("");
      return;
    }

    setActiveRun(batch.batch_id, activeRun.run_id);
    setActiveDetailTab(batch.batch_id, activeDetailTab);
    renderRunTabs(batch, activeRun.run_id);
    renderBatchFlowBoard(batch, activeRun.run_id);
    renderRunDetail(activeRun, activeDetailTab);
  }

  function clearActiveBatchView() {
    batchWorkspaceState.activeBatch = null;
    batchWorkspaceState.activeBatchId = null;
    batchWorkspaceState.activeDetailTab = DETAIL_TABS[0].id;
    $("#work_status_empty").prop("hidden", false);
    $("#work_status_content").prop("hidden", true);
    $("#batch_flow_panel").prop("hidden", true);
    $("#batch_flow_board").empty();
    $("#batch_flow_caption").text("");
    $("#batch_detail_tabs").empty();
  }

  function loadBatch(batchId, options) {
    if (!batchId) {
      clearActiveBatchView();
      return;
    }
    showWorkStatusSection("최근 배치와 이슈별 작업 상태를 추적한다.");
    $.getJSON(`/api/workflow/batch/${encodeURIComponent(batchId)}`)
      .done((data) => {
        if (!data.ok) {
          clearActiveBatchView();
          return;
        }
        const freezeClarificationRender = clarificationEditorFocused();
        if (freezeClarificationRender) {
          batchWorkspaceState.activeBatch = data;
          batchWorkspaceState.activeBatchId = data.batch_id;
          safeStorageSet(STORAGE_KEYS.activeBatchId, data.batch_id);
        } else {
          renderActiveBatch(data, options);
        }
        if ((!options || !options.silentListRefresh) && !freezeClarificationRender) {
          loadRecentBatches(batchId, true);
        }
        if (currentBatchShouldPoll(data)) {
          scheduleBatchPoll(batchId);
        } else {
          stopBatchPolling();
        }
      })
      .fail((xhr) => {
        stopBatchPolling();
        clearActiveBatchView();
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }

  function chooseDefaultBatch(batches, preferredBatchId) {
    if (preferredBatchId && batches.some((batch) => String(batch.batch_id) === String(preferredBatchId))) {
      return preferredBatchId;
    }
    const stored = safeStorageGet(STORAGE_KEYS.activeBatchId);
    if (stored && batches.some((batch) => String(batch.batch_id) === String(stored))) {
      return stored;
    }
    const active = batches.find((batch) => ["running", "queued", "needs_input"].includes(String(batch.status || "").trim()));
    if (active) {
      return active.batch_id;
    }
    return batches[0] ? batches[0].batch_id : "";
  }

  function loadRecentBatches(preferredBatchId, preserveSelection) {
    $.getJSON("/api/workflow/batches?limit=12")
      .done((data) => {
        const batches = data.batches || [];
        batchWorkspaceState.recentBatches = batches;
        if (!batches.length) {
          $("#work_status_section").prop("hidden", true);
          clearActiveBatchView();
          return;
        }
        showWorkStatusSection("최근 배치와 이슈별 작업 상태를 추적한다.");
        const nextBatchId = chooseDefaultBatch(batches, preferredBatchId || batchWorkspaceState.activeBatchId);
        if (nextBatchId) {
          loadBatch(nextBatchId, { preserveSelection: preserveSelection !== false, silentListRefresh: true });
        }
      })
      .fail((xhr) => {
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }

  function collectRunAnswers() {
    const answers = {};
    $("#batch_run_clarification_questions [data-batch-clarification-answer]").each(function () {
      const field = String($(this).attr("data-batch-clarification-answer") || "").trim();
      const value = String($(this).val() || "").trim();
      if (field && value) {
        answers[field] = value;
      }
    });
    return answers;
  }

  function submitActiveRunAnswers() {
    const batch = batchWorkspaceState.activeBatch;
    if (!batch) {
      return;
    }
    const runId = String($("#submit_batch_run_answers").data("runId") || "").trim();
    if (!runId) {
      return;
    }
    const answers = collectRunAnswers();
    if (!Object.keys(answers).length) {
      setResult("#workflow_result", { ok: false, error: "clarification_answers_missing", message: "질문에 대한 답변을 입력해 주세요." });
      return;
    }
    $.ajax({
      url: `/api/workflow/batch/${encodeURIComponent(batch.batch_id)}/runs/${encodeURIComponent(runId)}/answers`,
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ clarification_answers: answers }),
    })
      .done((data) => {
        clearClarificationDrafts(batch.batch_id, runId);
        setResult("#workflow_result", data);
        if (data.batch) {
          renderActiveBatch(data.batch, { preserveSelection: true });
        } else {
          loadBatch(batch.batch_id, { preserveSelection: true });
        }
      })
      .fail((xhr) => {
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }

  function runBatchAutomation(button) {
    const payload = workflowCommonPayload();
    if (!payload.issues.length) {
      setResult("#workflow_result", { ok: false, error: "batch_issues_required", message: "실행할 Jira 이슈를 하나 이상 선택해 주세요." });
      return;
    }
    if (!payload.work_instruction) {
      const requestedInformation = requestedInfoForFields(["work_instruction"]);
      setResult("#workflow_result", {
        ok: false,
        error: "workflow_fields_missing",
        fields: ["work_instruction"],
        requested_information: requestedInformation,
        message: "작업 지시 상세를 입력해 주세요.",
      });
      renderCallout("#workflow_result_actions", requestedInformation);
      focusFields(["work_instruction"]);
      return;
    }

    clearResultActions("#workflow_result_actions");
    button.prop("disabled", true).text("배치 실행 중...");
    showWorkStatusSection("선택한 이슈 배치를 준비하고 있다.");
    setResult("#workflow_result", { ok: true, status: "queued", message: `선택한 이슈 ${payload.issues.length}건의 배치 실행을 접수했다.` });

    $.ajax({
      url: "/api/workflow/batch/run",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(payload),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        button.prop("disabled", false).text("선택 이슈 배치 실행");
        if (data.batch_id) {
          loadRecentBatches(data.batch_id, true);
          loadBatch(data.batch_id, { preserveSelection: true, silentListRefresh: true });
        } else {
          loadRecentBatches("", true);
        }
      })
      .fail((xhr) => {
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
        button.prop("disabled", false).text("선택 이슈 배치 실행");
      });
  }

  function focusPriorityRun() {
    const batch = batchWorkspaceState.activeBatch;
    if (!batch || !(batch.runs || []).length) {
      return;
    }
    const priority = { running: 0, needs_input: 1, failed: 2, queued: 3, completed: 4 };
    const nextRun = (batch.runs || []).slice().sort((left, right) => {
      return (priority[left.status] || 9) - (priority[right.status] || 9);
    })[0];
    if (!nextRun) {
      return;
    }
    setActiveRun(batch.batch_id, nextRun.run_id);
    renderActiveBatch(batch, { preserveSelection: true });
  }

  $(document).ready(function () {
    window.selectedIssue = primarySelectedIssue;
    window.setupIssueTable = renderIssueTable;
    try {
      selectedIssue = primarySelectedIssue;
      setupIssueTable = renderIssueTable;
    } catch (error) {
      // noop
    }

    $("#workflow_clarification_panel").prop("hidden", true);
    $("#automation_result_section").prop("hidden", true);
    $("#work_status_section").prop("hidden", true);

    renderSelectionSummary();
    setBatchPreviewEmpty("이슈를 선택하면 미리보기를 표시한다.");
    loadRecentBatches("", true);

    $(document).on("change", "input[name='selected_issues']", function () {
      if (typeof jiraState !== "undefined") {
        jiraState.expandedIssueKey = String($(this).data("key") || "").trim();
        jiraState.issueAccordionCollapsed = false;
      }
      if (typeof syncIssueAccordionState === "function") {
        syncIssueAccordionState();
      }
      syncPrimaryIssueFields();
      renderSelectionSummary();
      const issue = primarySelectedIssue();
      if (issue && typeof loadIssueDetail === "function") {
        loadIssueDetail(issue.issue_key);
      } else if (typeof resetIssueDetail === "function") {
        resetIssueDetail();
      }
      scheduleBatchPreview();
    });

    $(document).on("click", "[data-run-id]", function () {
      const batch = batchWorkspaceState.activeBatch;
      const runId = String($(this).attr("data-run-id") || "").trim();
      if (!batch || !runId) {
        return;
      }
      setActiveRun(batch.batch_id, runId);
      renderActiveBatch(batch, { preserveSelection: true });
    });

    $(document).on("click", "[data-detail-tab]", function () {
      const batch = batchWorkspaceState.activeBatch;
      const detailTab = String($(this).attr("data-detail-tab") || "").trim();
      if (!batch || !detailTab) {
        return;
      }
      setActiveDetailTab(batch.batch_id, detailTab);
      renderActiveBatch(batch, { preserveSelection: true });
    });

    $(document).on("input", "[data-batch-clarification-answer]", function () {
      const batchId = batchWorkspaceState.activeBatchId;
      const runId = String($("#submit_batch_run_answers").data("runId") || "").trim();
      const field = String($(this).attr("data-batch-clarification-answer") || "").trim();
      if (!batchId || !runId || !field) {
        return;
      }
      setClarificationDraftValue(batchId, runId, field, String($(this).val() || ""));
    });

    $("#clear_issue_selection").on("click", function () {
      $("input[name='selected_issues']").prop("checked", false);
      syncPrimaryIssueFields();
      renderSelectionSummary();
      if (typeof resetIssueDetail === "function") {
        resetIssueDetail();
      }
      scheduleBatchPreview();
    });

    $("#prepare_workflow").off("click").on("click", function () {
      syncPrimaryIssueFields();
      requestBatchPreview();
    });

    $("#run_automation").off("click").on("click", function () {
      runBatchAutomation($(this));
    });

    $("#submit_batch_run_answers").on("click", function () {
      submitActiveRunAnswers();
    });

    $("#refresh_batch_workspace").on("click", function () {
      if (batchWorkspaceState.activeBatchId) {
        loadRecentBatches(batchWorkspaceState.activeBatchId, true);
      } else {
        loadRecentBatches("", true);
      }
    });

    $("#focus_running_run").on("click", function () {
      focusPriorityRun();
    });

    $("#toggle_failed_runs").on("click", function () {
      batchWorkspaceState.failedOnly = !batchWorkspaceState.failedOnly;
      $(this)
        .attr("aria-pressed", batchWorkspaceState.failedOnly ? "true" : "false")
        .text(batchWorkspaceState.failedOnly ? "전체 탭 보기" : "실패 탭만 보기");
      if (batchWorkspaceState.activeBatch) {
        renderActiveBatch(batchWorkspaceState.activeBatch, { preserveSelection: true });
      }
    });
  });
  renderRunOverview = function (run, payload) {
    const latestEvent = typeof latestWorkflowEvent === "function" ? latestWorkflowEvent(run) : null;
    const phaseLabels = typeof WORKFLOW_PHASE_LABELS === "object" ? WORKFLOW_PHASE_LABELS : {};
    const syntaxReturncode = payload.syntax_check_returncode != null ? payload.syntax_check_returncode : payload.test_returncode;
    const syntaxFiles = payload.syntax_checked_files || [];
    const cards = [
      setSummaryCard("상태", run.status || payload.status || "-", run.message || payload.message || ""),
      setSummaryCard("현재 단계", latestEvent ? (phaseLabels[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
      setSummaryCard("경과 시간", typeof workflowElapsedLabel === "function" ? workflowElapsedLabel(run) : "-", payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초` : ""),
      setSummaryCard("모델", payload.resolved_model || payload.requested_model || "-", payload.resolved_reasoning_effort ? `reasoning: ${payload.resolved_reasoning_effort}` : ""),
      setSummaryCard("저장소", run.resolved_repo_ref || payload.remote_repo_ref || "-", run.resolved_repo_provider || payload.remote_provider || ""),
      setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
      setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
      setSummaryCard("원격 Push", payload.push_succeeded ? "성공" : (payload.allow_auto_push ? "실패/미실행" : "비활성"), payload.remote_branch || ""),
      setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxFiles.length ? `대상 파일 ${syntaxFiles.length}개` : (payload.test_command || "")),
      setSummaryCard("업데이트", formatTimestamp(run.updated_at || run.finished_at || run.started_at || run.created_at)),
    ].join("");
    $("#batch_run_overview").html(cards);
  };
})(jQuery);
