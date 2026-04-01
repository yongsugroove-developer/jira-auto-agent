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

function setResult(id, payload) {
  $(id).text(JSON.stringify(payload, null, 2));
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

$(document).ready(function () {
  $("#load_config").on("click", function () {
    $.getJSON("/api/config")
      .done((data) => {
        fillConfig(data);
        setResult("#config_result", { ok: true, message: "저장값을 불러왔습니다." });
      })
      .fail((xhr) => setResult("#config_result", { ok: false, error: xhr.responseText }));
  });

  $("#validate_config").on("click", function () {
    $.ajax({
      url: "/api/config/validate",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(collectConfig()),
    })
      .done((data) => setResult("#config_result", data))
      .fail((xhr) => setResult("#config_result", { ok: false, error: xhr.responseText }));
  });

  $("#save_config").on("click", function () {
    $.ajax({
      url: "/api/config/save",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify(collectConfig()),
    })
      .done((data) => setResult("#config_result", data))
      .fail((xhr) => setResult("#config_result", xhr.responseJSON || { ok: false, error: xhr.responseText }));
  });

  $("#load_backlog").on("click", function () {
    $.ajax({
      url: "/api/jira/backlog",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ mock_mode: $("#mock_mode").is(":checked") }),
    })
      .done((data) => {
        const rows = (data.issues || []).map((issue, idx) => {
          return `
            <tr>
              <td>${issue.key}</td>
              <td>${issue.summary}</td>
              <td>${issue.status}</td>
              <td><input type="radio" name="selected_issue" ${idx === 0 ? "checked" : ""}
                  data-key="${issue.key}" data-summary="${issue.summary}"></td>
            </tr>
          `;
        });
        $("#issue_table").html(rows.join(""));
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
      setResult("#workflow_result", { ok: false, error: "이슈를 먼저 선택하세요." });
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
