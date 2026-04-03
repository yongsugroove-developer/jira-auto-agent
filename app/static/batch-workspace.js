(function ($) {
  const batchWorkspaceState = {
    previewTimer: null,
    pollTimer: null,
    preview: null,
    recentBatches: [],
    activeBatch: null,
    activeBatchId: null,
    failedOnly: false,
  };

  const STORAGE_KEYS = {
    activeBatchId: "jira-auto-agent.active-batch-id",
  };

  function batchRunStorageKey(batchId) {
    return `jira-auto-agent.active-run.${String(batchId || "").trim()}`;
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
    $("#selected_issue_count").text(`선택한 이슈 ${issues.length}건`);
    $("#selected_issue_keys").text(
      issues.length
        ? issues.map((issue) => `${issue.issue_key} ${issue.issue_summary}`).join(" / ")
        : "이슈를 선택하면 여기에서 배치 대상을 요약한다."
    );
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
          <div>저장소 ${escapeHtml(`${item.repo_owner}/${item.repo_name}`)}</div>
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
    const rows = issues.map((issue, index) => {
      const checked = index === 0 ? 'checked="checked"' : "";
      return `
        <tr>
          <td>${escapeHtml(issue.key || "")}</td>
          <td>${escapeHtml(issue.summary || "")}</td>
          <td>${escapeHtml(issue.status || "")}</td>
          <td>
            <input
              type="checkbox"
              name="selected_issues"
              ${checked}
              data-key="${escapeHtml(issue.key || "")}"
              data-summary="${escapeHtml(issue.summary || "")}"
            >
          </td>
        </tr>
      `;
    }).join("");
    $("#issue_table").html(rows);
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
    if (status === "queued" || status === "running" || status === "needs_input") {
      return true;
    }
    const runs = batch.runs || [];
    return runs.some((run) => ["queued", "running", "needs_input"].includes(String(run.status || "").trim()));
  }

  function scheduleBatchPoll(batchId) {
    stopBatchPolling();
    batchWorkspaceState.pollTimer = window.setTimeout(() => {
      loadBatch(batchId, { preserveSelection: true, silentListRefresh: false });
    }, 2000);
  }

  function renderBatchList(batches) {
    batchWorkspaceState.recentBatches = batches || [];
    if (!batchWorkspaceState.recentBatches.length) {
      $("#batch_list").html('<p class="batch-list__empty">실행한 배치가 아직 없다.</p>');
      return;
    }

    const cards = batchWorkspaceState.recentBatches.map((batch) => {
      const isActive = String(batch.batch_id) === String(batchWorkspaceState.activeBatchId || "");
      const counts = batch.counts || {};
      const countText = [
        `완료 ${counts.completed || 0}`,
        `실패 ${counts.failed || 0}`,
        `확인 ${counts.needs_input || 0}`,
      ].join(" / ");
      return `
        <button type="button" class="batch-list-item ${isActive ? "is-active" : ""}" data-batch-id="${escapeHtml(batch.batch_id)}">
          <div class="batch-list-item__header">
            <div class="batch-list-item__title">
              <strong>${escapeHtml(batch.batch_id.slice(0, 10))}</strong>
              <span>${escapeHtml((batch.selected_issue_keys || []).join(", ") || "이슈 정보 없음")}</span>
            </div>
            ${statusBadge(batch.status)}
          </div>
          <div class="batch-list-item__meta">
            <div>${escapeHtml(countText)}</div>
            <div>업데이트 ${escapeHtml(formatTimestamp(batch.updated_at))}</div>
          </div>
        </button>
      `;
    }).join("");
    $("#batch_list").html(cards);
  }

  function renderBatchSummary(batch) {
    const counts = batch.counts || {};
    const cards = [
      setSummaryCard("배치 ID", String(batch.batch_id || "").slice(0, 10) || "-", batch.message || ""),
      setSummaryCard("상태", batch.status || "-", `업데이트 ${formatTimestamp(batch.updated_at)}`),
      setSummaryCard("전체 이슈", String(counts.total || 0), (batch.selected_issue_keys || []).join(", ")),
      setSummaryCard("완료", String(counts.completed || 0), `실패 ${counts.failed || 0}`),
      setSummaryCard("추가 확인", String(counts.needs_input || 0), `대기 ${counts.queued || 0}`),
      setSummaryCard("활성 탭", batch.active_run_id || "-", batch.suggested_active_run_id ? `추천 ${batch.suggested_active_run_id}` : ""),
    ].join("");
    $("#batch_summary_cards").html(cards);
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

  function renderRunTabs(batch, activeRunId) {
    const runs = visibleRuns(batch);
    const tabs = runs.map((run) => {
      const isActive = String(run.run_id) === String(activeRunId);
      const queueText = run.queue_state === "queued" && run.queue_position ? `큐 ${run.queue_position}` : (run.queue_state || "");
      return `
        <button
          type="button"
          class="workspace-tab ${isActive ? "is-active" : ""}"
          role="tab"
          aria-selected="${isActive ? "true" : "false"}"
          data-run-id="${escapeHtml(run.run_id)}"
        >
          <span class="workspace-tab__meta">
            <strong>${escapeHtml(run.tab_label || run.issue_key || run.run_id)}</strong>
            <small>${escapeHtml(queueText || run.status || "")}</small>
          </span>
        </button>
      `;
    }).join("");
    $("#batch_run_tabs").html(tabs || '<p class="batch-list__empty">표시할 실행 탭이 없다.</p>');
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
      setSummaryCard("업데이트", formatTimestamp(run.updated_at || run.finished_at || run.started_at || run.created_at), run.run_id || ""),
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
    const editable = String(run.status || "").trim() === "needs_input" && requested.length > 0;

    renderText(
      "#batch_run_clarification_summary",
      clarification.analysis_summary || run.message || "",
      "추가 확인이 필요한 경우 이슈 탭 안에서 질문과 답변을 처리한다."
    );

    if (requested.length) {
      const questionItems = requested.map((item) => {
        const answer = String(answers[item.field] || "").trim();
        return `
          <label class="clarification-question">
            <span class="clarification-question__label">${escapeHtml(item.label || item.field)}</span>
            <strong class="clarification-question__prompt">${escapeHtml(item.question || "")}</strong>
            <small class="clarification-question__reason">${escapeHtml(item.why || "")}</small>
            ${editable ? `
              <textarea
                rows="3"
                data-batch-clarification-answer="${escapeHtml(item.field)}"
                placeholder="${escapeHtml(item.placeholder || "답변을 입력하세요.")}"
              >${escapeHtml(answer)}</textarea>
            ` : `
              <div class="clarification-answer-item">
                <strong>${escapeHtml(item.label || item.field)}</strong>
                <p>${escapeHtml(answer || "답변 없음")}</p>
              </div>
            `}
          </label>
        `;
      }).join("");
      $("#batch_run_clarification_questions").html(questionItems);
    } else {
      $("#batch_run_clarification_questions").html('<p class="batch-preview-empty">추가 질문이 없다.</p>');
    }

    if (!editable && Object.keys(answers).length) {
      const answerItems = Object.entries(answers).map(([field, answer]) => `
        <article class="clarification-answer-item">
          <strong>${escapeHtml(field)}</strong>
          <p>${escapeHtml(answer)}</p>
        </article>
      `).join("");
      $("#batch_run_clarification_answers").html(answerItems);
    } else {
      $("#batch_run_clarification_answers").empty();
    }

    $("#batch_run_clarification_actions").prop("hidden", !editable);
    $("#submit_batch_run_answers").data("runId", run.run_id);
  }

  function renderRunSync(run, payload) {
    const syncData = run.jira_comment_sync || payload.jira_comment_sync || null;
    if (typeof renderJiraCommentSync === "function") {
      renderJiraCommentSync("#batch_run_sync_status_list", "#batch_run_sync_status_card", syncData);
    }
  }

  function renderRunDetail(run) {
    const payload = runPayload(run);
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

    if (!activeRun) {
      $("#batch_run_tabs").html('<p class="batch-list__empty">표시할 실행 탭이 없다.</p>');
      $("#batch_run_meta").empty();
      return;
    }

    setActiveRun(batch.batch_id, activeRun.run_id);
    renderRunTabs(batch, activeRun.run_id);
    renderRunDetail(activeRun);
  }

  function clearActiveBatchView() {
    batchWorkspaceState.activeBatch = null;
    batchWorkspaceState.activeBatchId = null;
    $("#work_status_empty").prop("hidden", false);
    $("#work_status_content").prop("hidden", true);
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
        renderActiveBatch(data, options);
        if (!options || !options.silentListRefresh) {
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
        renderBatchList(batches);
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
        setResult("#workflow_result", data);
        if (data.batch) {
          renderActiveBatch(data.batch, { preserveSelection: true });
          renderBatchList(batchWorkspaceState.recentBatches);
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

    $(document).on("click", "[data-batch-id]", function () {
      const batchId = String($(this).attr("data-batch-id") || "").trim();
      if (!batchId) {
        return;
      }
      loadBatch(batchId, { preserveSelection: true });
      loadRecentBatches(batchId, true);
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
})(jQuery);
