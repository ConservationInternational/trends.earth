from qgis.testing import unittest

import sys
from queue import Queue
from time import sleep

from LDMP.test.test_dialog_settings import SettingsSuite

# Class to store GEE tasks that have been submitted for processing and that 
# have further tests to apply once the results have been returned. Queue stores 
# tuples of (GEE Task ID, settings object)
class  GEETaskList(object):
    def __init__(self):
        tasks = {}

    def put(self, task_id, status):
        if tasks.has_key(task_id):
            raise(Exception, 'Task ID {} is already in task list'.format(task_id))
        tasks[task_id] = status

    def get(self):
        if task.is_finished():
            return task
        else:
            # if the task isn't finished, add it back onto the queue (at the 
            # end, so another task will come up for consideration next time)
            self.put(task)
            return None

    def update_status(self):
        pass

    def empty(self):
        return True

gee_task_queue = GEETaskList()

def unitTests():
    _tests = []
    _tests.extend(SettingsSuite())
    return _tests

def run_all():
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(SettingsSuite())
    while True:
        if not gee_task_queue.empty():
            # update status of all items in the queue
            # process the next available task if it is ready
            gee_task_queue.update_status()
            task = gee_task_queue.get()
            while task:
                if task:
                    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(unittest.makeSuite(gee_task_queue.get()[1]))
        else:
            break
        print('Waiting for completion of GEE tasks')
        sleep(10)
