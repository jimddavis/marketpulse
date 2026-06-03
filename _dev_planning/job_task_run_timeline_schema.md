# Job Task Run Timeline Table Schema

URL:  https://docs.databricks.com/aws/en/admin/system-tables/jobs#task-timeline

## Description

The job task run timeline table is immutable and complete at the time it is produced.

**Table Path:** `system.lakeflow.job_task_run_timeline`

| Column Name | Data Type | Description | Notes |
|------------|-----------|-------------|-------|
| account_id | string | The ID of the account this job belongs to | |
| workspace_id | string | The ID of the workspace this job belongs to | |
| job_id | string | The ID of the job | Only unique within a single workspace |
| run_id | string | The ID of the task run | |
| job_run_id | string | The ID of the job run | |
| parent_run_id | string | The ID of the parent run | |
| period_start_time | timestamp | The start time for the task or for the time period | Timezone information is recorded at the end of the value with `+00:00` representing UTC. For details on how Databricks slices long runs into hourly intervals, see timeline slicing logic. |
| period_end_time | timestamp | The end time for the task or for the time period | Timezone information is recorded at the end of the value with `+00:00` representing UTC. For details on how Databricks slices long runs into hourly intervals, see timeline slicing logic. |
| task_key | string | The reference key for a task in a job | This key is only unique within a single job |
| compute_ids | array | The compute_ids array contains IDs of job clusters, interactive clusters, and SQL warehouses used by the job task | |
| result_state | string | The outcome of the job task run | For task runs longer than one hour that are split across multiple rows, this column is populated only in the row that represents the end of the run. |
| termination_code | string | The termination code of the task run | For task runs longer than one hour that are split across multiple rows, this column is populated only in the row that represents the end of the run. |
| compute | array | Details about the compute resources used in the job task run | Not populated for rows emitted before early December 2025 |
| termination_type | string | The type of termination for the job task run | Not populated for rows emitted before early December 2025 |
| task_parameters | map | The task-level parameters used in the job task run | Contains only the values from `job_parameters`. Deprecated parameter fields (`notebook_params`, `python_params`, `python_named_params`, `spark_submit_params`, and `sql_params`) are not included. Not populated for rows emitted before early December 2025. |
| setup_duration_seconds | long | The duration of the setup phase for the task run in seconds | Not populated for rows emitted before early December 2025 |
| cleanup_duration_seconds | long | The duration of the cleanup phase for the task run in seconds | Not populated for rows emitted before early December 2025 |
| execution_duration_seconds | long | The duration of the execution phase for the task run in seconds | Not populated for rows emitted before early December 2025 |

## Notes

- The table is immutable.
- Long-running tasks may be split across multiple timeline rows.
- Newer columns (`compute`, `termination_type`, `task_parameters`, and duration columns) are only populated for records emitted from early December 2025 onward.
