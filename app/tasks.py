import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

# Global task store
# Format: {task_id: {'status': 'pending'|'running'|'completed'|'failed', 'progress': 0, 'message': '', 'result': None}}
tasks = {}

# Executor for background tasks
executor = ThreadPoolExecutor(max_workers=3)

def start_task(func, *args, **kwargs):
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        'status': 'pending',
        'progress': 0,
        'message': 'Starting...',
        'total_bytes': 0,
        'downloaded_bytes': 0
    }
    
    def task_wrapper():
        try:
            tasks[task_id]['status'] = 'running'
            result = func(task_id, *args, **kwargs)
            tasks[task_id]['status'] = 'completed'
            tasks[task_id]['progress'] = 100
            tasks[task_id]['result'] = result
        except Exception as e:
            tasks[task_id]['status'] = 'failed'
            tasks[task_id]['message'] = str(e)
            
    executor.submit(task_wrapper)
    return task_id

def get_task_progress(task_id):
    return tasks.get(task_id)

def update_task_progress(task_id, progress=None, message=None, total_bytes=None, downloaded_bytes=None):
    if task_id in tasks:
        if progress is not None:
            tasks[task_id]['progress'] = progress
        if message is not None:
            tasks[task_id]['message'] = message
        if total_bytes is not None:
            tasks[task_id]['total_bytes'] = total_bytes
        if downloaded_bytes is not None:
            tasks[task_id]['downloaded_bytes'] = downloaded_bytes

def monitor_batch_completion(task_ids, callback):
    """
    Monitors a list of task_ids in a background thread.
    Executes callback() when all tasks are completed (or failed).
    """
    def monitor():
        import time
        print(f"Monitoring batch of {len(task_ids)} tasks...")
        while True:
            all_done = True
            for tid in task_ids:
                task = tasks.get(tid)
                if not task or task['status'] in ['pending', 'running']:
                    all_done = False
                    break
            
            if all_done:
                print("Batch completed. Executing callback...")
                try:
                    callback()
                except Exception as e:
                    print(f"Error in batch callback: {e}")
                break
            
            time.sleep(2)
            
    executor.submit(monitor)
