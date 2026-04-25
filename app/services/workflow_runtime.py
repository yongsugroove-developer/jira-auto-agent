from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    from app.domain.models import PendingWorkflowJob
except ModuleNotFoundError as exc:
    if exc.name != "app":
        raise
    from domain.models import PendingWorkflowJob


class WorkflowRuntime:
    def __init__(
        self,
        *,
        workflow_runs_dir: Path,
        workflow_batches_dir: Path,
        recent_batches_limit: int,
        stale_statuses: set[str],
        utcnow_iso: Callable[[], str],
        new_batch_factory: Callable[[list[dict[str, str]]], dict[str, Any]],
        workflow_run_snapshot: Callable[[dict[str, Any]], dict[str, Any]],
        workflow_batch_snapshot: Callable[[dict[str, Any]], dict[str, Any]],
        workflow_batch_run_ref: Callable[[dict[str, Any]], dict[str, Any]],
        workflow_log_ref: Callable[[dict[str, Any]], dict[str, Any]],
        workflow_log_sort_timestamp: Callable[[dict[str, Any]], str],
        batch_aggregate_status: Callable[[list[dict[str, Any]]], tuple[str, dict[str, int]]],
        batch_suggested_active_run_id: Callable[[list[dict[str, Any]]], str | None],
        batch_status_message: Callable[[str, dict[str, int]], str],
        save_workflow_run: Callable[[dict[str, Any]], None],
        load_workflow_run: Callable[[str], dict[str, Any] | None],
        save_workflow_batch: Callable[[dict[str, Any]], None],
        load_workflow_batch: Callable[[str], dict[str, Any] | None],
        mark_workflow_run_stale: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
    ) -> None:
        self.workflow_runs_dir = workflow_runs_dir
        self.workflow_batches_dir = workflow_batches_dir
        self.recent_batches_limit = recent_batches_limit
        self.stale_statuses = set(stale_statuses)
        self._utcnow_iso = utcnow_iso
        self._new_batch_factory = new_batch_factory
        self._workflow_run_snapshot = workflow_run_snapshot
        self._workflow_batch_snapshot = workflow_batch_snapshot
        self._workflow_batch_run_ref = workflow_batch_run_ref
        self._workflow_log_ref = workflow_log_ref
        self._workflow_log_sort_timestamp = workflow_log_sort_timestamp
        self._batch_aggregate_status = batch_aggregate_status
        self._batch_suggested_active_run_id = batch_suggested_active_run_id
        self._batch_status_message = batch_status_message
        self._save_workflow_run = save_workflow_run
        self._load_workflow_run = load_workflow_run
        self._save_workflow_batch = save_workflow_batch
        self._load_workflow_batch = load_workflow_batch
        self._mark_workflow_run_stale = mark_workflow_run_stale

        self.workflow_runs: dict[str, dict[str, Any]] = {}
        self.workflow_runs_lock = threading.Lock()
        self.workflow_batches: dict[str, dict[str, Any]] = {}
        self.workflow_batches_lock = threading.Lock()
        self.workflow_queue_pending: dict[str, list[PendingWorkflowJob]] = {}
        self.workflow_queue_active: set[str] = set()
        self.workflow_queue_lock = threading.Lock()
        self.workflow_run_cancel_events: dict[str, threading.Event] = {}
        self.workflow_run_processes: dict[str, Any] = {}
        self.workflow_run_controls_lock = threading.Lock()

    def load_batch_file_ids(self, limit: int | None = None) -> list[str]:
        if not self.workflow_batches_dir.exists():
            return []
        batch_files = sorted(
            self.workflow_batches_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if limit is not None:
            batch_files = batch_files[:limit]
        return [item.stem for item in batch_files]

    def load_run_file_ids(self, limit: int | None = None) -> list[str]:
        if not self.workflow_runs_dir.exists():
            return []
        run_files = sorted(
            self.workflow_runs_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if limit is not None:
            run_files = run_files[:limit]
        return [item.stem for item in run_files]

    def iter_known_run_snapshots(self) -> Iterator[dict[str, Any]]:
        seen_run_ids: set[str] = set()
        with self.workflow_runs_lock:
            loaded_runs = [self._workflow_run_snapshot(run) for run in self.workflow_runs.values()]
        for run in loaded_runs:
            run_id = str(run.get("run_id", "")).strip()
            if not run_id or run_id in seen_run_ids:
                continue
            seen_run_ids.add(run_id)
            yield run
        for run_id in self.load_run_file_ids():
            run_id = str(run_id).strip()
            if not run_id or run_id in seen_run_ids:
                continue
            persisted_run = self._load_workflow_run(run_id)
            if persisted_run is None:
                continue
            seen_run_ids.add(run_id)
            yield persisted_run

    def recover_batch_from_runs(self, batch_id: str) -> dict[str, Any] | None:
        normalized_batch_id = str(batch_id).strip()
        if not normalized_batch_id:
            return None

        matched_runs = [
            run_snapshot
            for run_snapshot in self.iter_known_run_snapshots()
            if str(run_snapshot.get("batch_id", "")).strip() == normalized_batch_id
        ]
        if not matched_runs:
            return None

        created_candidates = [
            str(run_snapshot.get("created_at", "")).strip()
            for run_snapshot in matched_runs
            if str(run_snapshot.get("created_at", "")).strip()
        ]
        created_at = min(created_candidates, default=self._utcnow_iso())
        updated_candidates = [
            str(
                run_snapshot.get("updated_at")
                or run_snapshot.get("finished_at")
                or run_snapshot.get("started_at")
                or run_snapshot.get("created_at")
                or ""
            ).strip()
            for run_snapshot in matched_runs
        ]
        updated_at = max([value for value in updated_candidates if value], default=created_at)
        selected_issue_keys = sorted(
            {
                str(run_snapshot.get("issue_key", "")).strip().upper()
                for run_snapshot in matched_runs
                if str(run_snapshot.get("issue_key", "")).strip()
            }
        )
        recovered_batch = {
            "batch_id": normalized_batch_id,
            "status": "queued",
            "message": "기존 실행 기록으로 배치 상태를 복구했다.",
            "created_at": created_at,
            "updated_at": updated_at,
            "active_run_id": None,
            "run_ids": [str(run_snapshot.get("run_id", "")).strip() for run_snapshot in matched_runs],
            "runs": [self._workflow_batch_run_ref(run_snapshot) for run_snapshot in matched_runs],
            "counts": {},
            "selected_issue_keys": selected_issue_keys,
            "selected_issue_count": len(selected_issue_keys),
        }
        with self.workflow_batches_lock:
            self.workflow_batches[normalized_batch_id] = recovered_batch
        self._save_workflow_batch(recovered_batch)
        return recovered_batch

    def load_active_batch_ids_from_runs(self, limit: int | None = None) -> list[str]:
        batch_ids: list[str] = []
        seen_batch_ids: set[str] = set()
        for run_snapshot in self.iter_known_run_snapshots():
            if str(run_snapshot.get("status", "")).strip() not in self.stale_statuses:
                continue
            batch_id = str(run_snapshot.get("batch_id", "")).strip()
            if not batch_id or batch_id in seen_batch_ids:
                continue
            seen_batch_ids.add(batch_id)
            batch_ids.append(batch_id)
            if limit is not None and len(batch_ids) >= limit:
                break
        return batch_ids

    def ensure_batch_loaded(self, batch_id: str) -> dict[str, Any] | None:
        with self.workflow_batches_lock:
            batch = self.workflow_batches.get(batch_id)
            if batch is not None:
                return batch
        persisted_batch = self._load_workflow_batch(batch_id)
        if persisted_batch is None:
            persisted_batch = self.recover_batch_from_runs(batch_id)
            if persisted_batch is None:
                return None
        with self.workflow_batches_lock:
            self.workflow_batches.setdefault(batch_id, persisted_batch)
            return self.workflow_batches[batch_id]

    def refresh_batch_state(self, batch_id: str) -> dict[str, Any] | None:
        batch = self.ensure_batch_loaded(batch_id)
        if batch is None:
            return None

        run_ids = [str(run_id).strip() for run_id in batch.get("run_ids", []) if str(run_id).strip()]
        if not run_ids:
            run_ids = [str(item.get("run_id", "")).strip() for item in batch.get("runs", []) if str(item.get("run_id", "")).strip()]

        runs: list[dict[str, Any]] = []
        for fallback_ref, run_id in zip(batch.get("runs", []), run_ids):
            run_snapshot = self.get_run(run_id)
            if run_snapshot is None:
                fallback_copy = dict(fallback_ref)
                fallback_copy.setdefault("run_id", run_id)
                fallback_copy.setdefault("events", [])
                fallback_copy.setdefault("result", None)
                fallback_copy.setdefault("error", None)
                runs.append(fallback_copy)
                continue
            runs.append(run_snapshot)

        if len(runs) < len(run_ids):
            known_run_ids = {str(run.get("run_id", "")).strip() for run in runs}
            for run_id in run_ids:
                if run_id in known_run_ids:
                    continue
                run_snapshot = self.get_run(run_id)
                if run_snapshot is not None:
                    runs.append(run_snapshot)

        status, counts = self._batch_aggregate_status(runs)
        suggested_active_run_id = self._batch_suggested_active_run_id(runs)
        active_run_id = str(batch.get("active_run_id") or "").strip()
        valid_run_ids = {str(run.get("run_id", "")).strip() for run in runs}
        if active_run_id not in valid_run_ids:
            active_run_id = suggested_active_run_id
        updated_values = [
            str(batch.get("updated_at", "")).strip(),
            *[
                str(
                    run.get("updated_at")
                    or run.get("finished_at")
                    or run.get("started_at")
                    or run.get("created_at")
                    or ""
                ).strip()
                for run in runs
            ],
        ]
        updated_at = max([value for value in updated_values if value], default=batch.get("updated_at", batch.get("created_at", self._utcnow_iso())))
        snapshot_to_save: dict[str, Any] | None = None
        with self.workflow_batches_lock:
            current_batch = self.workflow_batches.get(batch_id, batch)
            previous_snapshot = self._workflow_batch_snapshot(current_batch)
            current_batch["status"] = status
            current_batch["counts"] = counts
            current_batch["message"] = self._batch_status_message(status, counts)
            current_batch["updated_at"] = updated_at
            current_batch["active_run_id"] = active_run_id
            current_batch["run_ids"] = [str(run.get("run_id", "")).strip() for run in runs]
            current_batch["runs"] = [self._workflow_batch_run_ref(run) for run in runs]
            self.workflow_batches[batch_id] = current_batch
            snapshot = self._workflow_batch_snapshot(current_batch)
            if snapshot != previous_snapshot:
                snapshot_to_save = snapshot
        if snapshot_to_save is not None:
            self._save_workflow_batch(snapshot_to_save)
        return {**snapshot, "runs": runs, "suggested_active_run_id": suggested_active_run_id}

    def sync_batch_from_run_snapshot(self, run_snapshot: dict[str, Any]) -> None:
        batch_id = str(run_snapshot.get("batch_id", "")).strip()
        if not batch_id:
            return
        batch = self.ensure_batch_loaded(batch_id)
        if batch is None:
            return
        with self.workflow_batches_lock:
            run_id = str(run_snapshot.get("run_id", "")).strip()
            run_ids = [str(item).strip() for item in batch.get("run_ids", []) if str(item).strip()]
            if run_id and run_id not in run_ids:
                run_ids.append(run_id)
            batch["run_ids"] = run_ids
            refs = [dict(item) for item in batch.get("runs", [])]
            refs_by_id = {str(item.get("run_id", "")).strip(): item for item in refs}
            refs_by_id[run_id] = self._workflow_batch_run_ref(run_snapshot)
            batch["runs"] = [refs_by_id[item_id] for item_id in run_ids if item_id in refs_by_id]
            batch["updated_at"] = str(run_snapshot.get("updated_at") or self._utcnow_iso())
        self.refresh_batch_state(batch_id)

    def register_run(self, run: dict[str, Any]) -> None:
        snapshot = {}
        with self.workflow_runs_lock:
            self.workflow_runs[run["run_id"]] = run
            self._save_workflow_run(run)
            snapshot = self._workflow_run_snapshot(run)
        self.sync_batch_from_run_snapshot(snapshot)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.workflow_runs_lock:
            run = self.workflow_runs.get(run_id)
            if run is not None:
                return self._workflow_run_snapshot(run)

        persisted_run = self._load_workflow_run(run_id)
        if persisted_run is None:
            return None

        persisted_run, changed = self._mark_workflow_run_stale(persisted_run)
        if changed:
            self._save_workflow_run(persisted_run)
            self.sync_batch_from_run_snapshot(persisted_run)
        return persisted_run

    def update_run(self, run_id: str, updater: Any) -> dict[str, Any] | None:
        snapshot: dict[str, Any] | None = None
        with self.workflow_runs_lock:
            run = self.workflow_runs.get(run_id)
            if run is None:
                persisted_run = self._load_workflow_run(run_id)
                if persisted_run is None:
                    return None
                persisted_run, changed = self._mark_workflow_run_stale(persisted_run)
                run = persisted_run
                self.workflow_runs[run_id] = run
                if changed:
                    self._save_workflow_run(run)
            updater(run)
            self._save_workflow_run(run)
            snapshot = self._workflow_run_snapshot(run)
        if snapshot is not None:
            self.sync_batch_from_run_snapshot(snapshot)
        return snapshot

    def create_batch(self, issues: list[dict[str, str]]) -> dict[str, Any]:
        batch = self._new_batch_factory(issues)
        with self.workflow_batches_lock:
            self.workflow_batches[batch["batch_id"]] = batch
            self._save_workflow_batch(batch)
        return batch

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        return self.refresh_batch_state(batch_id)

    def list_batches(self, limit: int | None = None) -> list[dict[str, Any]]:
        active_statuses = self.stale_statuses
        effective_limit = limit or self.recent_batches_limit
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        with self.workflow_batches_lock:
            loaded_batch_ids = list(self.workflow_batches.keys())
        candidate_ids = [
            *loaded_batch_ids,
            *self.load_batch_file_ids(limit=effective_limit * 2),
            *self.load_active_batch_ids_from_runs(limit=effective_limit * 2),
        ]
        for batch_id in candidate_ids:
            batch_id = str(batch_id).strip()
            if not batch_id or batch_id in seen_ids:
                continue
            seen_ids.add(batch_id)
            batch_snapshot = self.get_batch(batch_id)
            if batch_snapshot is None:
                continue
            results.append(self._workflow_batch_snapshot(batch_snapshot))
        results.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        results.sort(key=lambda item: 0 if str(item.get("status", "")).strip() in active_statuses else 1)
        return results[:effective_limit]

    def list_workflow_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        with self.workflow_runs_lock:
            loaded_run_ids = list(self.workflow_runs.keys())
        candidate_ids = [*loaded_run_ids, *self.load_run_file_ids(limit=limit * 4)]
        for run_id in candidate_ids:
            run_id = str(run_id).strip()
            if not run_id or run_id in seen_ids:
                continue
            seen_ids.add(run_id)
            run_snapshot = self.get_run(run_id)
            if run_snapshot is None:
                continue
            results.append(self._workflow_log_ref(run_snapshot))
        results.sort(key=lambda item: self._workflow_log_sort_timestamp(item), reverse=True)
        return results[:limit]

    def update_pending_queue_positions(self, queue_key: str, update_run: Callable[[str, Any], dict[str, Any] | None]) -> None:
        pending_jobs = self.workflow_queue_pending.get(queue_key, [])
        for index, pending_job in enumerate(pending_jobs, start=1):
            update_run(
                pending_job.run_id,
                lambda run, idx=index: (
                    run.__setitem__("queue_state", "queued"),
                    run.__setitem__("queue_position", idx),
                ),
            )

    def ensure_workflow_run_cancel_event(self, run_id: str) -> threading.Event:
        with self.workflow_run_controls_lock:
            event = self.workflow_run_cancel_events.get(run_id)
            if event is None:
                event = threading.Event()
                self.workflow_run_cancel_events[run_id] = event
            return event

    def track_workflow_run_process(self, run_id: str, process: Any | None) -> None:
        with self.workflow_run_controls_lock:
            if process is None:
                self.workflow_run_processes.pop(run_id, None)
                return
            self.workflow_run_processes[run_id] = process

    def clear_workflow_run_controls(self, run_id: str) -> None:
        with self.workflow_run_controls_lock:
            self.workflow_run_cancel_events.pop(run_id, None)
            self.workflow_run_processes.pop(run_id, None)

    def request_workflow_run_cancel(self, run_id: str, *, stop_process: Callable[[Any, str], None]) -> bool:
        cancel_event = self.ensure_workflow_run_cancel_event(run_id)
        cancel_event.set()
        process = None
        with self.workflow_run_controls_lock:
            process = self.workflow_run_processes.get(run_id)
        if process is None:
            return False
        stop_process(process, name=f"workflow-run-{run_id}")
        return True

    def remove_pending_workflow_job(self, run_id: str, queue_key: str, *, update_run: Callable[[str, Any], dict[str, Any] | None]) -> bool:
        removed = False
        with self.workflow_queue_lock:
            pending_jobs = self.workflow_queue_pending.get(queue_key, [])
            remaining_jobs = [job for job in pending_jobs if job.run_id != run_id]
            removed = len(remaining_jobs) != len(pending_jobs)
            if removed:
                if remaining_jobs:
                    self.workflow_queue_pending[queue_key] = remaining_jobs
                else:
                    self.workflow_queue_pending.pop(queue_key, None)
                self.update_pending_queue_positions(queue_key, update_run)
        return removed

    def start_next_queued_job_locked(self, queue_key: str, *, update_run: Callable[[str, Any], dict[str, Any] | None]) -> PendingWorkflowJob | None:
        pending_jobs = self.workflow_queue_pending.get(queue_key, [])
        if queue_key in self.workflow_queue_active or not pending_jobs:
            return None
        job = pending_jobs.pop(0)
        if not pending_jobs:
            self.workflow_queue_pending.pop(queue_key, None)
        self.workflow_queue_active.add(queue_key)
        self.update_pending_queue_positions(queue_key, update_run)
        return job

    def enqueue_workflow_run(
        self,
        job: PendingWorkflowJob,
        *,
        normalize_queue_key: Callable[[Any], str],
        update_run: Callable[[str, Any], dict[str, Any] | None],
        utcnow_iso: Callable[[], str],
        start_workflow_execution: Callable[[PendingWorkflowJob, str], None],
    ) -> None:
        queue_key = normalize_queue_key(job.repo_path)
        update_run(
            job.run_id,
            lambda run: (
                run.__setitem__("queue_key", queue_key),
                run.__setitem__("queue_state", "queued"),
                run.__setitem__("queue_position", len(self.workflow_queue_pending.get(queue_key, [])) + (1 if queue_key in self.workflow_queue_active else 0) + 1),
                run.__setitem__("status", "queued"),
                run.__setitem__("message", "실행 큐에 등록했습니다."),
                run.__setitem__("updated_at", utcnow_iso()),
            ),
        )
        job_to_start: PendingWorkflowJob | None = None
        with self.workflow_queue_lock:
            self.workflow_queue_pending.setdefault(queue_key, []).append(job)
            self.update_pending_queue_positions(queue_key, update_run)
            job_to_start = self.start_next_queued_job_locked(queue_key, update_run=update_run)
        if job_to_start is not None:
            start_workflow_execution(job_to_start, queue_key)

    def finish_queue_job(
        self,
        queue_key: str,
        *,
        update_run: Callable[[str, Any], dict[str, Any] | None],
        start_workflow_execution: Callable[[PendingWorkflowJob, str], None],
    ) -> None:
        job_to_start: PendingWorkflowJob | None = None
        with self.workflow_queue_lock:
            self.workflow_queue_active.discard(queue_key)
            self.update_pending_queue_positions(queue_key, update_run)
            job_to_start = self.start_next_queued_job_locked(queue_key, update_run=update_run)
        if job_to_start is not None:
            start_workflow_execution(job_to_start, queue_key)
