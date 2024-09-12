from qgis.core import QgsApplication, QgsTask
from qgis.utils import iface

from te_schemas.algorithms import AlgorithmRunMode

def submit_job(job_manager, payload, script_id, job_type, task):
    """Function that submits a job and runs in a task."""
    try:
        if job_type == AlgorithmRunMode.REMOTE:
            job = job_manager.submit_remote_job(payload, script_id)
        elif job_type == AlgorithmRunMode.LOCAL:
            job = job_manager.submit_local_job(payload, script_id, aoi)

        return job
    except Exception as e:
        return None


def create_task(job_manager, payload, script_id, job_type, task_finished=None, aoi=None):
    # Create a task using fromFunction
    if task_finished is None:
        task_finished = on_task_finished

    task = QgsTask.fromFunction(
        "Submit Job",
        submit_job,
        on_finished=task_finished,
        job_manager=job_manager,
        payload=payload,
        script_id=script_id,
        job_type=job_type,
        aoi=aoi
    )

    QgsApplication.taskManager().addTask(task)

    return task

def on_task_finished(exception, result=None):
    if exception is None:
        if result:
            print(f"Task completed successfully, job: {result}")
        else:
            print("Task completed but no job returned.")
    else:
        print(f"Task failed: {exception}")
