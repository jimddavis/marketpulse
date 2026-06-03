
Possibly use this API to do auditing of job runs and creating a report of some kind.



# Find some job tasks that failed
  SELECT runid FROM system.lakeflow.job_task_run_timeline
  where result_state != 'SUCCEEDED'
  order by period_start_time desc
LIMIT 10;





from databricks.sdk import WorkspaceClient

# Initialize the client
w = WorkspaceClient()

        # get_run_output retrieves the stdout/stderr/error of a specific task
output = w.jobs.get_run_output(run_id=529876357863261)    # hard coded id from above query just for demonstration

    # Check for error messages or logs
if output.error:
    print(output.error)


Outputs

UnknownException: (com.amazonaws.services.s3.model.AmazonS3Exception) Bad Request; request: HEAD https://dbstorage-prod-lcu04.s3.us-east-2.amazonaws.com uc/8dc07b48-46c1-418b-b0cb-c29978f9ae19/6fa6b000-cb1d-486e-9002-43be6541cff2/__unitystorage/catalogs/dfbc6b3f-b6f5-4286-b9c0-6146a32ab23b/tables/4a9e83f9-edb6-44be-9c1f-f2d27f316d47/_delta_log/00000000000000000029.json {} Hadoop 3.4.2, aws-sdk-java/1.12.681 Linux/6.1.166-197.305.amzn2023.aarch64 OpenJDK_64-Bit_Server_VM/17.0.18+8-LTS java/17.0.18 scala/2.13.16 kotlin/1.9.10 vendor/Azul_Systems,_Inc. cfg/retry-mode/legacy com.amazonaws.services.s3.model.GetObjectMetadataRequest; Request ID: THKY1JVC8EXA320M, Extended Request ID: RR6QEssWzDV3upBukwbIlxKc6K8Z7f1ofiM1YvIChLcng0OTN3bJESpvNzJoLCGr6hZ++oS1SKMqS8bYqkvFKwXtWYxW4sVi, Cloud Provider: AWS, Instance ID: unknown (Service: Amazon S3; Status Code: 400; Error Code: 400 Bad Request; Request ID: THKY1JVC8EXA320M; S3 Extended Request ID: RR6QEssWzDV3upBukwbIlxKc6K8Z7f1ofiM1YvIChLcng0OTN3bJESpvNzJoLCGr6hZ++oS1SKMqS8bYqkvFKwXtWYxW4sVi; Proxy: null)

JVM stacktrace:
com.amazonaws.services.s3.model.AmazonS3Exception
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.handleErrorResponse(AmazonHttpClient.java:1879)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.handleServiceErrorResponse(AmazonHttpClient.java:1418)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.executeOneRequest(AmazonHttpClient.java:1387)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.executeHelper(AmazonHttpClient.java:1157)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.doExecute(AmazonHttpClient.java:814)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.executeWithTimer(AmazonHttpClient.java:781)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.execute(AmazonHttpClient.java:755)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutor.access$500(AmazonHttpClient.java:715)
	at com.amazonaws.http.AmazonHttpClient$RequestExecutionBuilderImpl.execute(AmazonHttpClient.java:697)
	at com.amazonaws.http.AmazonHttpClient.execute(AmazonHttpClient.java:561)



	workspace.jobs is documented at https://databricks-sdk-py.readthedocs.io/en/latest/workspace/jobs/jobs.html

	get_run_output() returns a RunOutput object.  Defined at https://databricks-sdk-py.readthedocs.io/en/latest/dbdataclasses/jobs.html#databricks.sdk.service.jobs.RunOutput as


	lass databricks.sdk.service.jobs.RunOutput(alert_output: AlertTaskOutput | None = None, clean_rooms_notebook_output: CleanRoomsNotebookTaskCleanRoomsNotebookTaskOutput | None = None, dashboard_output: DashboardTaskOutput | None = None, dbt_cloud_output: DbtCloudTaskOutput | None = None, dbt_output: DbtOutput | None = None, dbt_platform_output: DbtPlatformTaskOutput | None = None, error: str | None = None, error_trace: str | None = None, info: str | None = None, logs: str | None = None, logs_truncated: bool | None = None, metadata: Run | None = None, notebook_output: NotebookOutput | None = None, run_job_output: RunJobOutput | None = None, sql_output: SqlOutput | None = None)
Run output was retrieved successfully.

alert_output: AlertTaskOutput | None = None
The output of an alert task, if available

clean_rooms_notebook_output: CleanRoomsNotebookTaskCleanRoomsNotebookTaskOutput | None = None
The output of a clean rooms notebook task, if available

dashboard_output: DashboardTaskOutput | None = None
The output of a dashboard task, if available

dbt_cloud_output: DbtCloudTaskOutput | None = None
Deprecated in favor of the new dbt_platform_output

dbt_output: DbtOutput | None = None
The output of a dbt task, if available.

dbt_platform_output: DbtPlatformTaskOutput | None = None
error: str | None = None
An error message indicating why a task failed or why output is not available. The message is unstructured, and its exact format is subject to change.

error_trace: str | None = None
If there was an error executing the run, this field contains any available stack traces.

info: str | None = None
logs: str | None = None
The output from tasks that write to standard streams (stdout/stderr) such as spark_jar_task, spark_python_task, python_wheel_task.

It’s not supported for the notebook_task, pipeline_task or spark_submit_task.

Databricks restricts this API to return the last 5 MB of these logs.

logs_truncated: bool | None = None
Whether the logs are truncated.

metadata: Run | None = None
All details of the run except for its output.

notebook_output: NotebookOutput | None = None
The output of a notebook task, if available. A notebook task that terminates (either successfully or with a failure) without calling dbutils.notebook.exit() is considered to have an empty output. This field is set but its result value is empty. Databricks restricts this API to return the first 5 MB of the output. To return a larger result, use the [ClusterLogConf] field to configure log storage for the job cluster.

[ClusterLogConf]: https://docs.databricks.com/dev-tools/api/latest/clusters.html#clusterlogconf

run_job_output: RunJobOutput | None = None
The output of a run job task, if available

sql_output: SqlOutput | None = None
The output of a SQL task, if available.

as_dict() → dict
Serializes the RunOutput into a dictionary suitable for use as a JSON request body.

as_shallow_dict() → dict
Serializes the RunOutput into a shallow dictionary of its immediate attributes.

classmethod from_dict(d: Dict[str, Any]) → RunOutput
Deserializes the RunOutput from a dictionary.







