(function ($) {
  const batchWorkspaceState = {
    previewTimer: null,
    pollTimer: null,
    previewRequest: null,
    batchRunRequest: null,
    preview: null,
    recentBatches: [],
    activeBatch: null,
    activeBatchId: null,
    activeDetailTab: "overview",
    activeMonitorTab: "active",
    clarificationDrafts: {},
    clarificationSubmissionPending: {},
  };

  const STORAGE_KEYS = {
    activeBatchId: "jira-auto-agent.active-batch-id",
    activeMonitorTab: "jira-auto-agent.monitor-tab",
  };

  const DETAIL_TABS = [
    { id: "overview", label: "실행 개요" },
    { id: "summary", label: "결과 요약" },
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

  const ACTIVE_RUN_STATUSES = ["queued", "running", "needs_input", "pending_plan_review"];

  function batchRunStorageKey(batchId) {
    return `jira-auto-agent.active-run.${String(batchId || "").trim()}`;
  }

  function batchDetailStorageKey(batchId) {
    return `jira-auto-agent.active-detail.${String(batchId || "").trim()}`;
  }

  function clarificationDraftKey(batchId, runId) {
    return `${String(batchId || "").trim()}:${String(runId || "").trim()}`;
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function isOptimisticBatch(batch) {
    return String((batch && batch.batch_id) || "").trim() === "pending-batch";
  }

  function clearPreviewRequest() {
    batchWorkspaceState.previewRequest = null;
  }

  function clearBatchRunRequest() {
    batchWorkspaceState.batchRunRequest = null;
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

  function safeStorageRemove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      return;
    }
  }

  function preferredMonitorTab() {
    const stored = String(safeStorageGet(STORAGE_KEYS.activeMonitorTab) || "").trim();
    return stored === "logs" ? "logs" : "active";
  }

  function renderMonitoringPanels() {
    const activeMonitorTab = batchWorkspaceState.activeMonitorTab === "logs" ? "logs" : "active";
    $("#work_status_section").prop("hidden", activeMonitorTab !== "active");
    $("#workflow_log_section").prop("hidden", activeMonitorTab !== "logs");
    $("#monitoring_tabs [data-monitor-tab]").each(function () {
      const isActive = String($(this).attr("data-monitor-tab") || "").trim() === activeMonitorTab;
      $(this)
        .toggleClass("is-active", isActive)
        .attr("aria-selected", isActive ? "true" : "false");
    });
  }

  function setActiveMonitorTab(tab) {
    const normalized = String(tab || "").trim() === "logs" ? "logs" : "active";
    batchWorkspaceState.activeMonitorTab = normalized;
    safeStorageSet(STORAGE_KEYS.activeMonitorTab, normalized);
    renderMonitoringPanels();
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
      agent_provider: String($("#agent_provider").val() || window.__AGENT_PROVIDER_DEFAULT__ || "codex").trim() || "codex",
      codex_model: String($("#codex_model").val() || "").trim(),
      codex_reasoning_effort: String($("#codex_reasoning_effort").val() || "").trim(),
      claude_model: String($("#claude_model").val() || "").trim(),
      claude_permission_mode: String($("#claude_permission_mode").val() || "").trim(),
      work_instruction: String($("#work_instruction").val() || "").trim(),
      acceptance_criteria: String($("#acceptance_criteria").val() || "").trim(),
      test_command: String($("#test_command").val() || "").trim(),
      commit_checklist: String($("#commit_checklist").val() || "").trim(),
      git_author_name: String($("#git_author_name").val() || "").trim(),
      git_author_email: String($("#git_author_email").val() || "").trim(),
      allow_auto_commit: $("#allow_auto_commit").is(":checked"),
      allow_auto_push: $("#allow_auto_push").is(":checked"),
      enable_plan_review: $("#enable_plan_review").is(":checked"),
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

    if (batchWorkspaceState.previewRequest && typeof batchWorkspaceState.previewRequest.abort === "function") {
      batchWorkspaceState.previewRequest.abort();
    }

    batchWorkspaceState.previewRequest = $.ajax({
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
        if (xhr && xhr.statusText === "abort") {
          return;
        }
        setBatchPreviewEmpty("미리보기를 불러오지 못했다.");
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      })
      .always(() => {
        clearPreviewRequest();
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
    if (typeof window.populateIssueBacklog === "function") {
      window.populateIssueBacklog({ issues }, {
        inputType: "checkbox",
        inputName: "selected_issues",
      });
    } else {
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
      const issue = primarySelectedIssue();
      if (issue && typeof loadIssueDetail === "function") {
        loadIssueDetail(issue.issue_key);
      } else if (typeof resetIssueDetail === "function") {
        resetIssueDetail();
      }
    }
    syncPrimaryIssueFields();
    renderSelectionSummary();
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

  function statusText(status) {
    const normalized = String(status || "").trim() || "idle";
    const labels = {
      queued: "대기",
      running: "실행",
      completed: "완료",
      failed: "실패",
      cancelled: "취소됨",
      needs_input: "추가 확인",
      pending_plan_review: "계획 확인",
      partially_completed: "부분 완료",
      idle: "대기",
      finished: "종료",
    };
    return labels[normalized] || normalized;
  }

  function statusBadge(status) {
    const normalized = String(status || "").trim() || "idle";
    return `<span class="status-badge is-${escapeHtml(normalized)}">${escapeHtml(statusText(normalized))}</span>`;
  }

  function workflowLogSummary(label, value) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    return `<p class="workflow-log-item__summary"><strong>${escapeHtml(label)}</strong>${escapeHtml(text)}</p>`;
  }

  function renderWorkflowLogs(data) {
    const logs = (data && data.logs) || [];
    $("#workflow_log_caption").text(logs.length ? `최근 처리된 작업 ${logs.length}건 요약` : "저장된 작업 로그가 없다.");
    if (!logs.length) {
      $("#workflow_log_list").html('<p class="batch-list__empty">저장된 작업 로그가 없다.</p>');
      renderMonitoringPanels();
      return;
    }

    const cards = logs.map((item) => `
      <article class="workflow-log-item">
        <div class="workflow-log-item__header">
          <div class="workflow-log-item__headline">
            <strong>${escapeHtml(item.issue_key || "-")}</strong>
            <span>${escapeHtml(item.issue_summary || "제목 없음")}</span>
          </div>
          <div class="batch-list-item__pills">
            ${statusBadge(item.status)}
          </div>
        </div>
        <div class="workflow-log-item__meta">
          <div>에이전트 ${escapeHtml(item.resolved_agent_label || item.agent_provider || "-")}</div>
          <div>모델 ${escapeHtml(item.resolved_agent_model || "-")}</div>
          <div>실행 모드 ${escapeHtml(item.resolved_agent_execution_mode || "-")}</div>
          <div>공간 ${escapeHtml(item.resolved_space_key || "-")}</div>
          <div>저장소 ${escapeHtml(item.resolved_repo_ref || "-")}</div>
          <div>브랜치 ${escapeHtml(item.branch_name || "-")}</div>
          <div>업데이트 ${escapeHtml(formatTimestamp(item.updated_at || item.finished_at || item.created_at))}</div>
        </div>
        <p class="workflow-log-item__message">${escapeHtml(item.message || item.latest_phase_message || "-")}</p>
        <div class="workflow-log-item__summaries">
          ${workflowLogSummary("의도", item.intent_summary)}
          ${workflowLogSummary("구현", item.implementation_summary)}
          ${workflowLogSummary("검증", item.validation_summary)}
        </div>
      </article>
    `).join("");
    $("#workflow_log_list").html(cards);
    renderMonitoringPanels();
    if (typeof window.syncWorkspaceShellHeight === "function") {
      window.syncWorkspaceShellHeight(false);
    }
  }

  function loadWorkflowLogs() {
    $.getJSON("/api/workflow/logs?limit=40")
      .done((data) => {
        renderWorkflowLogs(data);
      })
      .fail((xhr) => {
        $("#workflow_log_caption").text("작업 로그를 불러오지 못했다.");
        $("#workflow_log_list").html('<p class="batch-list__empty">작업 로그를 불러오지 못했다.</p>');
        renderMonitoringPanels();
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
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
    renderMonitoringPanels();
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

  function currentClarificationSubmission(batchId, runId) {
    return batchWorkspaceState.clarificationSubmissionPending[clarificationDraftKey(batchId, runId)] || null;
  }

  function setClarificationDraftValue(batchId, runId, field, value) {
    const key = clarificationDraftKey(batchId, runId);
    const drafts = { ...currentClarificationDrafts(batchId, runId) };
    drafts[field] = value;
    batchWorkspaceState.clarificationDrafts[key] = drafts;
  }

  function setClarificationSubmissionPending(batchId, runId, answers) {
    batchWorkspaceState.clarificationSubmissionPending[clarificationDraftKey(batchId, runId)] = {
      answers: { ...(answers || {}) },
      submittedAt: new Date().toISOString(),
    };
  }

  function clearClarificationDrafts(batchId, runId) {
    delete batchWorkspaceState.clarificationDrafts[clarificationDraftKey(batchId, runId)];
  }

  function clearClarificationSubmissionPending(batchId, runId) {
    delete batchWorkspaceState.clarificationSubmissionPending[clarificationDraftKey(batchId, runId)];
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

  function isActiveRunStatus(status) {
    return ACTIVE_RUN_STATUSES.includes(String(status || "").trim());
  }

  function currentRuns(batch) {
    return (batch && batch.runs ? batch.runs : []).filter((run) => isActiveRunStatus(run.status));
  }

  function isCurrentBatch(batch) {
    if (!batch) {
      return false;
    }
    if (isActiveRunStatus(batch.status)) {
      return true;
    }
    return currentRuns(batch).length > 0;
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

  function summarizeBatchRuns(runs) {
    const counts = {
      queued: 0,
      running: 0,
      needs_input: 0,
      pending_plan_review: 0,
      completed: 0,
      failed: 0,
      cancelled: 0,
      partially_completed: 0,
      total: (runs || []).length,
    };
    (runs || []).forEach((run) => {
      const status = String(run.status || "").trim();
      if (Object.prototype.hasOwnProperty.call(counts, status)) {
        counts[status] += 1;
      } else {
        counts.queued += 1;
      }
    });
    return counts;
  }

  function aggregateBatchStatus(runs) {
    const counts = summarizeBatchRuns(runs);
    if (!counts.total) {
      return { status: "queued", counts };
    }
    if (counts.running > 0) {
      return { status: "running", counts };
    }
    if (counts.queued > 0) {
      return { status: "queued", counts };
    }
    if (counts.needs_input > 0) {
      return { status: "needs_input", counts };
    }
    if (counts.pending_plan_review > 0) {
      return { status: "pending_plan_review", counts };
    }
    if (counts.cancelled === counts.total) {
      return { status: "cancelled", counts };
    }
    if (counts.completed === counts.total) {
      return { status: "completed", counts };
    }
    if (counts.partially_completed === counts.total) {
      return { status: "partially_completed", counts };
    }
    if (counts.failed === counts.total) {
      return { status: "failed", counts };
    }
    return { status: "partially_completed", counts };
  }

  function buildPendingBatch(issues, provider) {
    const timestamp = new Date().toISOString();
    const agentProvider = String(provider || $("#agent_provider").val() || window.__AGENT_PROVIDER_DEFAULT__ || "codex").trim() || "codex";
    const runs = (issues || []).map((issue, index) => ({
      run_id: `pending-run-${index + 1}`,
      batch_id: "pending-batch",
      agent_provider: agentProvider,
      issue_key: String(issue.issue_key || "").trim(),
      issue_summary: String(issue.issue_summary || "").trim(),
      tab_label: `${String(issue.issue_key || "").trim()} ${String(issue.issue_summary || "").trim()}`.trim(),
      status: "queued",
      message: "요청을 접수했고 Jira 정보와 저장소 설정을 확인하는 중이다.",
      queue_key: "pending",
      queue_state: "queued",
      queue_position: index + 1,
      local_repo_path: "",
      resolved_space_key: "",
      clarification_status: "not_requested",
      clarification: null,
      request_payload: {
        agent_provider: agentProvider,
        issue_key: String(issue.issue_key || "").trim(),
        issue_summary: String(issue.issue_summary || "").trim(),
        enable_plan_review: $("#enable_plan_review").is(":checked"),
      },
      created_at: timestamp,
      started_at: null,
      finished_at: null,
      updated_at: timestamp,
      events: [
        {
          timestamp,
          phase: "queued",
          message: "요청을 접수했고 초기 데이터 수집을 시작했다.",
        },
      ],
      result: null,
      error: null,
    }));
    const summary = aggregateBatchStatus(runs);
    return {
      batch_id: "pending-batch",
      status: summary.status,
      message: "요청을 접수했고 초기 데이터 수집을 시작했다.",
      created_at: timestamp,
      updated_at: timestamp,
      active_run_id: runs[0] ? runs[0].run_id : "",
      run_ids: runs.map((run) => run.run_id),
      runs,
      counts: summary.counts,
      selected_issue_keys: runs.map((run) => run.issue_key),
      selected_issue_count: runs.length,
      suggested_active_run_id: runs[0] ? runs[0].run_id : "",
    };
  }

  function buildOptimisticClarificationBatch(batch, runId, answers) {
    const nextBatch = cloneJson(batch);
    const submittedAt = new Date().toISOString();
    nextBatch.runs = (nextBatch.runs || []).map((run) => {
      if (String(run.run_id || "").trim() !== String(runId || "").trim()) {
        return run;
      }
      const clarification = run.clarification || {};
      return {
        ...run,
        status: "queued",
        message: "답변을 제출했다. 작업 재개를 준비 중이다.",
        queue_state: "queued",
        queue_position: 0,
        clarification_status: "submitted",
        clarification: {
          analysis_summary: clarification.analysis_summary || run.message || "",
          requested_information: clarification.requested_information || [],
          answers: { ...(answers || {}) },
        },
        updated_at: submittedAt,
        events: [
          ...(run.events || []),
          {
            timestamp: submittedAt,
            phase: "queued",
            message: "답변을 제출했고 작업 재개를 준비 중이다.",
          },
        ],
      };
    });
    const summary = aggregateBatchStatus(nextBatch.runs || []);
    nextBatch.status = summary.status;
    nextBatch.counts = summary.counts;
    nextBatch.message = "답변을 제출했고 작업 재개를 준비 중이다.";
    nextBatch.updated_at = submittedAt;
    nextBatch.active_run_id = runId;
    nextBatch.suggested_active_run_id = runId;
    return nextBatch;
  }

  function renderBatchSummary(batch) {
    const counts = summarizeBatchRuns(currentRuns(batch));
    const cards = [
      setSummaryCard("배치 ID", String(batch.batch_id || "").slice(0, 10) || "-"),
      setSummaryCard("상태", statusText(batch.status || "-")),
      setSummaryCard("현재 이슈", `${counts.total || 0}건`),
      setSummaryCard("접수 대기", `${counts.queued || 0}건`),
      setSummaryCard("실행 중", `${counts.running || 0}건`),
      setSummaryCard("추가 확인", `${counts.needs_input || 0}건`),
      setSummaryCard("계획 확인", `${counts.pending_plan_review || 0}건`),
      setSummaryCard("최근 갱신", formatTimestamp(batch.updated_at || batch.created_at)),
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
    const runs = currentRuns(batch).map((run) => String(run.run_id || ""));
    if (stored && runs.includes(stored)) {
      return stored;
    }
    const visible = currentRuns(batch);
    return String(batch.active_run_id || batch.suggested_active_run_id || (visible[0] && visible[0].run_id) || "");
  }

  function visibleRuns(batch) {
    return currentRuns(batch);
  }

  function canCancelRun(run) {
    const status = String((run && run.status) || "").trim();
    const batchId = String((run && run.batch_id) || "").trim();
    if (batchId === "pending-batch") {
      return false;
    }
    return ["queued", "running", "needs_input", "pending_plan_review"].includes(status);
  }

  function activeFlowRuns(batch) {
    return currentRuns(batch);
  }

  function renderRunTabs(batch, activeRunId) {
    const runs = visibleRuns(batch);
    const tabs = runs.map((run) => {
      const isActive = String(run.run_id) === String(activeRunId);
      const title = String(run.issue_summary || run.tab_label || run.issue_key || run.run_id || "").trim();
      return `
        <div class="workspace-run-tab-row ${isActive ? "is-active" : ""}">
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
          ${canCancelRun(run) ? `
            <button
              type="button"
              class="workspace-run-tab__cancel"
              data-cancel-run-id="${escapeHtml(run.run_id)}"
              data-run-issue-key="${escapeHtml(run.issue_key || "")}"
            >
              작업 취소
            </button>
          ` : ""}
        </div>
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
    const provider = String(run.agent_provider || payload.agent_provider || (run.request_payload || {}).agent_provider || "codex").trim() || "codex";
    const providerLabel = payload.resolved_agent_label || (provider === "claude" ? "Claude Code" : "Codex");
    const items = [
      `<span class="field-pill">${escapeHtml(providerLabel)}</span>`,
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
    if (status === "pending_plan_review") {
      return "실행 전에 작업 계획 확인 승인을 기다린다.";
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
    } else if (status === "pending_plan_review") {
      activeStepId = "prepare";
    } else if (["completed", "failed", "partially_completed"].includes(status)) {
      activeStepId = "done";
    } else if (["syntax_start", "syntax_end", "stage_changes", "stage_ready", "commit_start", "commit_end"].includes(phase)) {
      activeStepId = "review";
    } else if (phase.startsWith("codex") || phase.startsWith("agent") || status === "running") {
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

    const counts = summarizeBatchRuns(runs);
    $("#batch_flow_caption").text(`접수 ${counts.queued}건 / 실행 ${counts.running}건 / 확인 ${counts.needs_input}건 / 계획 확인 ${counts.pending_plan_review}건 / 완료 ${counts.completed}건 / 실패 ${counts.failed + counts.partially_completed}건`);

    const rows = runs.map((run) => {
      const payload = runPayload(run);
      const flow = resolveFlowState(run, payload);
      const isActive = String(run.run_id) === String(activeRunId);
      const normalizedStatus = String(run.status || "").trim().replace(/_/g, "-") || "idle";
      const isProcessing = ["queued", "running", "needs_input"].includes(String(run.status || "").trim());
      const track = flow.steps.map((step) => `
        <div class="batch-flow-step ${step.className}" data-step-id="${escapeHtml(step.id)}">
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
      setSummaryCard("상태", statusText(run.status || payload.status || "-")),
      setSummaryCard("현재 단계", latestEvent ? (phaseLabels[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
      setSummaryCard("경과 시간", typeof workflowElapsedLabel === "function" ? workflowElapsedLabel(run) : "-", payload.codex_elapsed_seconds != null ? `Codex ${payload.codex_elapsed_seconds}초` : ""),
      setSummaryCard("모델", payload.resolved_model || payload.requested_model || "-", payload.resolved_reasoning_effort ? `reasoning: ${payload.resolved_reasoning_effort}` : ""),
      setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
      setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
      setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxFiles.length ? `대상 파일 ${syntaxFiles.length}개` : (payload.test_command || "")),
      setSummaryCard("업데이트", formatTimestamp(run.updated_at || run.finished_at || run.started_at || run.created_at)),
    ].join("");
    $("#batch_run_overview").html(cards);
    renderPlanReviewSection(run, payload);
  }

  function renderPlanMarkdown(markdown) {
    const html = [];
    const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
    let paragraph = [];
    let listItems = [];

    function flushParagraph() {
      if (!paragraph.length) {
        return;
      }
      html.push(`<p>${escapeHtml(paragraph.join(" ").trim())}</p>`);
      paragraph = [];
    }

    function flushList() {
      if (!listItems.length) {
        return;
      }
      html.push(`<ul>${listItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
      listItems = [];
    }

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        flushList();
        return;
      }
      if (trimmed.startsWith("## ")) {
        flushParagraph();
        flushList();
        html.push(`<h4>${escapeHtml(trimmed.slice(3).trim())}</h4>`);
        return;
      }
      if (/^[-*]\s+/.test(trimmed)) {
        flushParagraph();
        listItems.push(trimmed.replace(/^[-*]\s+/, "").trim());
        return;
      }
      if (/^\d+\.\s+/.test(trimmed)) {
        flushParagraph();
        listItems.push(trimmed.replace(/^\d+\.\s+/, "").trim());
        return;
      }
      flushList();
      paragraph.push(trimmed);
    });

    flushParagraph();
    flushList();
    return html.join("");
  }

  function buildPlanReviewMarkdown(planReview, run) {
    const summary = String(planReview.plan_summary || run.message || "실행 전 계획을 검토해 주세요.").trim();
    const steps = Array.isArray(planReview.implementation_steps) && planReview.implementation_steps.length
      ? planReview.implementation_steps.map((item) => `- ${String(item || "").trim()}`).join("\n")
      : "- 표시할 구현 단계가 없다.";
    const risks = Array.isArray(planReview.risks) && planReview.risks.length
      ? planReview.risks.map((item) => `- ${String(item || "").trim()}`).join("\n")
      : "- 표시할 리스크가 없다.";
    return {
      markdown: [
        "## 작업 요약",
        summary,
        "",
        "## 구현 단계",
        steps,
        "",
        "## 리스크 및 확인 사항",
        risks,
      ].join("\n"),
    };
  }

  function actionableRuns(batch) {
    return visibleRuns(batch).filter((run) => {
      const status = String(run.status || "").trim();
      return status === "needs_input" || status === "pending_plan_review";
    });
  }

  function renderActionCenterRunTabs(batch, activeRunId) {
    const host = $("#action_center_run_tabs");
    if (!host.length) {
      return;
    }
    const runs = batch ? actionableRuns(batch) : [];
    if (!runs.length) {
      host.empty().prop("hidden", true);
      return;
    }
    host.html(
      runs.map((run) => {
        const status = String(run.status || "").trim();
        const issueKey = String(run.issue_key || run.run_id || "").trim() || "작업";
        const isActive = String(run.run_id) === String(activeRunId);
        return `
          <button
            type="button"
            class="action-center-run-tab ${isActive ? "is-active" : ""}"
            data-action-center-run-id="${escapeHtml(run.run_id)}"
          >
            <span class="action-center-run-tab__issue">${escapeHtml(issueKey)}</span>
            <span class="action-center-run-tab__status">${escapeHtml(statusText(status))}</span>
          </button>
        `;
      }).join("")
    ).prop("hidden", false);
  }

  function syncActionCenterVisibility(batch, activeRunId) {
    renderActionCenterRunTabs(batch, activeRunId);
    const hasPlanReview = $("#batch_run_plan_review").length && !$("#batch_run_plan_review").prop("hidden");
    const hasClarification = $("#batch_run_clarification_card").length && !$("#batch_run_clarification_card").prop("hidden");
    const hasSyncStatus = $("#batch_run_sync_status_card").length && !$("#batch_run_sync_status_card").prop("hidden");
    const hasContent = Boolean(hasPlanReview || hasClarification || hasSyncStatus);

    $("#action_center_section").prop("hidden", false);
    $("#action_center_content").prop("hidden", !hasContent);
    $("#action_center_empty").prop("hidden", hasContent);
  }

  function ensurePlanReviewUi() {
    const card = $("#batch_run_plan_review");
    if (!card.length) {
      return;
    }
    if (!card.find("#batch_run_plan_markdown").length) {
      $('<div id="batch_run_plan_markdown" class="plan-review-markdown"></div>').insertAfter(card.find(".plan-review-card__header"));
    }
    let footer = card.find(".plan-review-card__footer");
    if (!footer.length) {
      footer = $('<div class="plan-review-card__footer"></div>');
      card.append(footer);
    }
    if (!footer.find("#cancel_batch_run_plan").length) {
      footer.append('<button id="cancel_batch_run_plan" type="button" class="secondary-button">계획 취소</button>');
    }
    const approveButton = $("#approve_batch_run_plan");
    if (approveButton.length && !footer.find("#approve_batch_run_plan").length) {
      footer.append(approveButton);
    }
    $("#batch_run_plan_summary").prop("hidden", true);
    $(".plan-review-card__content").prop("hidden", true);
  }

  function renderPlanReviewSection(run, payload) {
    ensurePlanReviewUi();
    const planReview = run.plan_review || payload.plan_review || {};
    const status = String(run.plan_review_status || "").trim();
    const visible = status === "pending_approval" && String(run.status || "").trim() === "pending_plan_review";
    $("#batch_run_plan_review").prop("hidden", !visible);
    if (!visible) {
      $("#batch_run_plan_markdown").html("<p>승인 대기 중인 계획이 없다.</p>");
      $("#approve_batch_run_plan").data("runId", "");
      $("#cancel_batch_run_plan").data("runId", "");
      return;
    }
    const markdownInfo = buildPlanReviewMarkdown(planReview, run);
    $("#batch_run_plan_markdown").html(renderPlanMarkdown(markdownInfo.markdown));
    $("#approve_batch_run_plan").data("runId", run.run_id).prop("disabled", false).text("이 계획으로 실행");
    $("#cancel_batch_run_plan").data("runId", run.run_id).prop("disabled", false).text("계획 취소");
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
    const pendingSubmission = currentClarificationSubmission(batchId, runId);
    const displayedAnswers = pendingSubmission ? pendingSubmission.answers || {} : answers;
    const hasAnswers = Object.keys(displayedAnswers).length > 0;
    const editable = String(run.status || "").trim() === "needs_input" && requested.length > 0 && !pendingSubmission;
    const visible = requested.length > 0 || pendingSubmission;
    const focusState = clarificationFocusState();
    const normalizedStatus = String(run.status || "").trim();

    $("#batch_run_clarification_card").prop("hidden", !visible);
    if (!visible) {
      $("#batch_run_clarification_summary").text("추가 확인이 필요한 경우 이 영역에서 질문과 답변을 처리한다.");
      $("#batch_run_clarification_state").empty();
      $("#batch_run_clarification_questions").empty().prop("hidden", true);
      $("#batch_run_clarification_answers").empty().prop("hidden", true);
      $("#batch_run_clarification_actions").prop("hidden", true);
      $("#submit_batch_run_answers").data("runId", "");
      return;
    }

    let stateVariant = "is-idle";
    let stateTitle = "추가 질문 없음";
    let stateMessage = "현재 배치에서 추가 입력이 필요한 질문이 없다.";
    if (pendingSubmission) {
      stateVariant = "is-submitted";
      stateTitle = "답변 제출 완료";
      stateMessage = "답변을 접수했다. 실행 개요 탭으로 이동했으며, 작업이 재개되면 진행 플로우에서 상태를 바로 확인할 수 있다.";
    } else if (editable && hasAnswers) {
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
          : String(displayedAnswers[item.field] || "");
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
      const answerItems = Object.entries(displayedAnswers).map(([field, answer]) => `
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

  function renderRunDetail(run, activeDetailTab, batch) {
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
    renderText(
      "#batch_run_test_output",
      payload.syntax_check_output || payload.test_output || payload.clarification_debug_text || payload.clarification_output_tail,
      "문법 검사 출력이나 사전 확인 로그가 없다.",
    );
    renderText("#batch_run_log", typeof eventLogText === "function" ? eventLogText(run.events) : "실행 로그 없음", "실행 로그 없음");
    syncActionCenterVisibility(batch, run.run_id);
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
    renderMonitoringPanels();
    $("#work_status_empty").prop("hidden", true);
    $("#work_status_content").prop("hidden", false);

    const runs = visibleRuns(batch);
    const activeRunId = preserveSelection
      ? preferredRunId(batch)
      : (preferredRunId(batch) || (runs[0] && runs[0].run_id));
    const actionRuns = actionableRuns(batch);
    let activeRun = runs.find((run) => String(run.run_id) === String(activeRunId)) || runs[0] || null;
    if (actionRuns.length && (!activeRun || !actionRuns.some((run) => String(run.run_id) === String(activeRun.run_id)))) {
      activeRun = actionRuns[0];
    }
    const activeDetailTab = preferredDetailTab(batch);

    if (!activeRun) {
      clearActiveBatchView();
      return;
    }

    setActiveRun(batch.batch_id, activeRun.run_id);
    setActiveDetailTab(batch.batch_id, activeDetailTab);
    renderRunTabs(batch, activeRun.run_id);
    renderBatchFlowBoard(batch, activeRun.run_id);
    renderRunDetail(activeRun, activeDetailTab, batch);
    if (typeof window.syncWorkspaceShellHeight === "function") {
      window.syncWorkspaceShellHeight(false);
    }
  }

  function clearActiveBatchView() {
    const previousBatchId = batchWorkspaceState.activeBatchId;
    batchWorkspaceState.activeBatch = null;
    batchWorkspaceState.activeBatchId = null;
    batchWorkspaceState.activeDetailTab = DETAIL_TABS[0].id;
    safeStorageRemove(STORAGE_KEYS.activeBatchId);
    if (previousBatchId) {
      safeStorageRemove(batchRunStorageKey(previousBatchId));
      safeStorageRemove(batchDetailStorageKey(previousBatchId));
    }
    $("#work_status_empty").prop("hidden", false);
    $("#work_status_content").prop("hidden", true);
    $("#batch_flow_panel").prop("hidden", true);
    $("#batch_flow_board").empty();
    $("#batch_flow_caption").text("");
    $("#batch_run_tabs").empty();
    $("#batch_detail_tabs").empty();
    $("#batch_run_meta").empty();
    $("#batch_run_overview").empty();
    $("#batch_run_plan_review").prop("hidden", true);
    $("#batch_run_plan_markdown").html("<p>승인 대기 중인 계획이 없다.</p>");
    $("#batch_run_clarification_card").prop("hidden", true);
    $("#batch_run_clarification_state").empty();
    $("#batch_run_clarification_questions").empty().prop("hidden", true);
    $("#batch_run_clarification_answers").empty().prop("hidden", true);
    $("#batch_run_clarification_actions").prop("hidden", true);
    $("#submit_batch_run_answers").data("runId", "");
    $("#batch_run_sync_status_card").prop("hidden", true);
    $("#batch_run_sync_status_list").empty();
    $("#action_center_run_tabs").empty().prop("hidden", true);
    setActiveMonitorTab("active");
    syncActionCenterVisibility(null, "");
    if (typeof window.syncWorkspaceShellHeight === "function") {
      window.syncWorkspaceShellHeight(false);
    }
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
        if (!isCurrentBatch(data)) {
          stopBatchPolling();
          loadRecentBatches("", true);
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
    const active = batches.find((batch) => isCurrentBatch(batch));
    if (active) {
      return active.batch_id;
    }
    return batches[0] ? batches[0].batch_id : "";
  }

  function loadRecentBatches(preferredBatchId, preserveSelection) {
    $.getJSON("/api/workflow/batches?limit=12")
      .done((data) => {
        loadWorkflowLogs();
        const batches = (data.batches || []).filter((batch) => isCurrentBatch(batch));
        batchWorkspaceState.recentBatches = batches;
        if (!batches.length) {
          showWorkStatusSection("현재 진행 중인 작업이 없습니다.");
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
    const originalBatch = cloneJson(batch);
    stopBatchPolling();
    clearResultActions("#workflow_result_actions");
    setClarificationSubmissionPending(batch.batch_id, runId, answers);
    setActiveDetailTab(batch.batch_id, "overview");
    setActiveMonitorTab("active");
    renderActiveBatch(buildOptimisticClarificationBatch(batch, runId, answers), { preserveSelection: true });
    setResult("#workflow_result", { ok: true, status: "queued", message: "답변을 제출했다. 작업 재개를 준비 중이다." });
    $.ajax({
      url: `/api/workflow/batch/${encodeURIComponent(batch.batch_id)}/runs/${encodeURIComponent(runId)}/answers`,
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ clarification_answers: answers }),
    })
      .done((data) => {
        clearClarificationSubmissionPending(batch.batch_id, runId);
        clearClarificationDrafts(batch.batch_id, runId);
        setResult("#workflow_result", data);
        if (data.batch) {
          renderActiveBatch(data.batch, { preserveSelection: true });
          if (currentBatchShouldPoll(data.batch)) {
            scheduleBatchPoll(data.batch.batch_id);
          }
        } else {
          loadBatch(batch.batch_id, { preserveSelection: true });
        }
      })
      .fail((xhr) => {
        clearClarificationSubmissionPending(batch.batch_id, runId);
        renderActiveBatch(originalBatch, { preserveSelection: true });
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }

  function approveActiveRunPlan(button) {
    const batch = batchWorkspaceState.activeBatch;
    if (!batch) {
      setResult("#workflow_result", { ok: false, error: "active_batch_required", message: "현재 선택된 배치를 찾을 수 없다." });
      return;
    }
    const runId = String(
      button.data("runId")
      || ((visibleRuns(batch).find((run) => String(run.status || "").trim() === "pending_plan_review") || {}).run_id)
      || ""
    ).trim();
    if (!runId) {
      setResult("#workflow_result", { ok: false, error: "plan_review_run_required", message: "실행할 계획 승인 대기 작업을 찾을 수 없다." });
      return;
    }
    clearResultActions("#workflow_result_actions");
    button.prop("disabled", true).text("실행 등록 중...");
    setActiveMonitorTab("active");
    $.ajax({
      url: `/api/workflow/batch/${encodeURIComponent(batch.batch_id)}/runs/${encodeURIComponent(runId)}/plan/approve`,
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({}),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        if (data.batch) {
          renderActiveBatch(data.batch, { preserveSelection: true });
          if (currentBatchShouldPoll(data.batch)) {
            scheduleBatchPoll(data.batch.batch_id);
          }
        } else {
          loadBatch(batch.batch_id, { preserveSelection: true });
        }
      })
      .fail((xhr) => {
        button.prop("disabled", false).text("이 계획으로 실행");
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }

  function cancelActiveRunPlan(button) {
    const batch = batchWorkspaceState.activeBatch;
    if (!batch) {
      setResult("#workflow_result", { ok: false, error: "active_batch_required", message: "현재 선택된 배치를 찾을 수 없다." });
      return;
    }
    const runId = String(
      button.data("runId")
      || ((visibleRuns(batch).find((run) => String(run.status || "").trim() === "pending_plan_review") || {}).run_id)
      || ""
    ).trim();
    if (!runId) {
      setResult("#workflow_result", { ok: false, error: "plan_review_run_required", message: "취소할 계획 승인 대기 작업을 찾을 수 없다." });
      return;
    }
    clearResultActions("#workflow_result_actions");
    button.prop("disabled", true).text("취소 처리 중...");
    $.ajax({
      url: `/api/workflow/batch/${encodeURIComponent(batch.batch_id)}/runs/${encodeURIComponent(runId)}/plan/cancel`,
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({}),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        loadWorkflowLogs();
        if (data.batch) {
          if (!isCurrentBatch(data.batch)) {
            stopBatchPolling();
            clearActiveBatchView();
            loadRecentBatches("", true);
            return;
          }
          renderActiveBatch(data.batch, { preserveSelection: true });
          if (currentBatchShouldPoll(data.batch)) {
            scheduleBatchPoll(data.batch.batch_id);
          }
        } else {
          loadRecentBatches("", true);
        }
      })
      .fail((xhr) => {
        button.prop("disabled", false).text("계획 취소");
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
      });
  }

  function cancelBatchRun(button) {
    const batch = batchWorkspaceState.activeBatch;
    if (!batch) {
      setResult("#workflow_result", { ok: false, error: "active_batch_required", message: "현재 선택된 배치를 찾을 수 없다." });
      return;
    }
    if (isOptimisticBatch(batch)) {
      if (batchWorkspaceState.batchRunRequest && typeof batchWorkspaceState.batchRunRequest.abort === "function") {
        batchWorkspaceState.batchRunRequest.abort();
      }
      if (batchWorkspaceState.previewTimer) {
        window.clearTimeout(batchWorkspaceState.previewTimer);
        batchWorkspaceState.previewTimer = null;
      }
      if (batchWorkspaceState.previewRequest && typeof batchWorkspaceState.previewRequest.abort === "function") {
        batchWorkspaceState.previewRequest.abort();
      }
      clearActiveBatchView();
      setResult("#workflow_result", { ok: true, status: "cancelled", message: "실행 접수를 취소했다." });
      return;
    }
    const runId = String(button.attr("data-cancel-run-id") || "").trim();
    if (!runId) {
      setResult("#workflow_result", { ok: false, error: "workflow_run_not_found", message: "취소할 작업을 찾을 수 없다." });
      return;
    }
    const originalLabel = button.text();
    clearResultActions("#workflow_result_actions");
    button.prop("disabled", true).text("취소 중...");
    $.ajax({
      url: `/api/workflow/batch/${encodeURIComponent(batch.batch_id)}/runs/${encodeURIComponent(runId)}/cancel`,
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({}),
    })
      .done((data) => {
        setResult("#workflow_result", data);
        loadWorkflowLogs();
        if (!data.batch) {
          loadRecentBatches("", true);
          return;
        }
        if (!isCurrentBatch(data.batch)) {
          stopBatchPolling();
          clearActiveBatchView();
          loadRecentBatches("", true);
          return;
        }
        renderActiveBatch(data.batch, { preserveSelection: true });
        if (currentBatchShouldPoll(data.batch) || data.status === "cancel_requested") {
          scheduleBatchPoll(data.batch.batch_id);
        }
      })
      .fail((xhr) => {
        button.prop("disabled", false).text(originalLabel);
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
    setActiveMonitorTab("active");
    showWorkStatusSection("선택한 이슈 배치를 준비하고 있다.");
    setResult("#workflow_result", { ok: true, status: "queued", message: `선택한 이슈 ${payload.issues.length}건의 배치 실행을 접수했다.` });
    renderActiveBatch(buildPendingBatch(payload.issues, payload.agent_provider), { preserveSelection: false });

    if (batchWorkspaceState.previewTimer) {
      window.clearTimeout(batchWorkspaceState.previewTimer);
      batchWorkspaceState.previewTimer = null;
    }
    if (batchWorkspaceState.previewRequest && typeof batchWorkspaceState.previewRequest.abort === "function") {
      batchWorkspaceState.previewRequest.abort();
    }

    batchWorkspaceState.batchRunRequest = $.ajax({
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
        if (xhr && xhr.statusText === "abort") {
          button.prop("disabled", false).text("선택 이슈 배치 실행");
          clearActiveBatchView();
          return;
        }
        setResult("#workflow_result", xhr.responseJSON || { ok: false, error: xhr.responseText });
        button.prop("disabled", false).text("선택 이슈 배치 실행");
        clearActiveBatchView();
      })
      .always(() => {
        clearBatchRunRequest();
      });
  }

  function focusPriorityRun() {
    const batch = batchWorkspaceState.activeBatch;
    const runs = visibleRuns(batch);
    if (!batch || !runs.length) {
      return;
    }
    const priority = { running: 0, needs_input: 1, pending_plan_review: 2, queued: 3 };
    const nextRun = runs.slice().sort((left, right) => {
      return (priority[left.status] || 9) - (priority[right.status] || 9);
    })[0];
    if (!nextRun) {
      return;
    }
    setActiveMonitorTab("active");
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

    renderSelectionSummary();
    setBatchPreviewEmpty("이슈를 선택하면 미리보기를 표시한다.");
    setActiveMonitorTab(preferredMonitorTab());
    syncActionCenterVisibility(null, "");
    loadWorkflowLogs();
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

    $(document).on("click", "[data-cancel-run-id]", function (event) {
      event.stopPropagation();
      cancelBatchRun($(this));
    });

    $(document).on("click", "[data-action-center-run-id]", function () {
      const batch = batchWorkspaceState.activeBatch;
      const runId = String($(this).attr("data-action-center-run-id") || "").trim();
      if (!batch || !runId) {
        return;
      }
      setActiveMonitorTab("active");
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

    $(document).on("click", "[data-monitor-tab]", function () {
      const monitorTab = String($(this).attr("data-monitor-tab") || "").trim();
      setActiveMonitorTab(monitorTab);
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

    $("#approve_batch_run_plan").on("click", function () {
      approveActiveRunPlan($(this));
    });

    $(document).on("click", "#cancel_batch_run_plan", function () {
      cancelActiveRunPlan($(this));
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

    $("#refresh_workflow_logs").on("click", function () {
      loadWorkflowLogs();
    });

  });
  renderRunOverview = function (run, payload) {
    const latestEvent = typeof latestWorkflowEvent === "function" ? latestWorkflowEvent(run) : null;
    const phaseLabels = typeof WORKFLOW_PHASE_LABELS === "object" ? WORKFLOW_PHASE_LABELS : {};
    const syntaxReturncode = payload.syntax_check_returncode != null ? payload.syntax_check_returncode : payload.test_returncode;
    const syntaxFiles = payload.syntax_checked_files || [];
    const provider = String(run.agent_provider || payload.agent_provider || (run.request_payload || {}).agent_provider || "codex").trim() || "codex";
    const providerLabel = payload.resolved_agent_label || (provider === "claude" ? "Claude Code" : "Codex");
    const modelLabel = payload.resolved_agent_model || payload.resolved_model || payload.requested_agent_model || payload.requested_model || "-";
    const executionValue = payload.resolved_agent_execution_mode || payload.resolved_reasoning_effort || payload.requested_agent_execution_mode || payload.requested_reasoning_effort || "";
    const elapsedSeconds = payload.agent_elapsed_seconds != null ? payload.agent_elapsed_seconds : payload.codex_elapsed_seconds;
    const cards = [
      setSummaryCard("상태", statusText(run.status || payload.status || "-")),
      setSummaryCard("현재 단계", latestEvent ? (phaseLabels[latestEvent.phase] || latestEvent.phase) : "-", latestEvent ? latestEvent.message : ""),
      setSummaryCard("Agent", providerLabel, payload.provider_metadata && payload.provider_metadata.execution_mode_label ? payload.provider_metadata.execution_mode_label : ""),
      setSummaryCard("경과 시간", typeof workflowElapsedLabel === "function" ? workflowElapsedLabel(run) : "-", elapsedSeconds != null ? `${providerLabel} ${elapsedSeconds}초` : ""),
      setSummaryCard("모델", modelLabel, executionValue ? (provider === "claude" ? `permission: ${executionValue}` : `reasoning: ${executionValue}`) : ""),
      setSummaryCard("저장소", run.resolved_repo_ref || payload.remote_repo_ref || "-", run.resolved_repo_provider || payload.remote_provider || ""),
      setSummaryCard("브랜치", payload.branch_name || "-", payload.current_branch ? `현재 브랜치 ${payload.current_branch}` : ""),
      setSummaryCard("커밋", payload.commit_sha || "-", payload.commit_message || ""),
      setSummaryCard("원격 Push", payload.push_succeeded ? "성공" : (payload.allow_auto_push ? "실패/미실행" : "비활성"), payload.remote_branch || ""),
      setSummaryCard("문법 검사", syntaxReturncode == null ? "-" : String(syntaxReturncode), syntaxFiles.length ? `대상 파일 ${syntaxFiles.length}개` : (payload.test_command || "")),
      setSummaryCard("업데이트", formatTimestamp(run.updated_at || run.finished_at || run.started_at || run.created_at)),
    ].join("");
    $("#batch_run_overview").html(cards);
    renderPlanReviewSection(run, payload);
  };
})(jQuery);

