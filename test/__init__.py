from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QMessageBox

# with open(
#     os.path.join(os.path.dirname(__file__), "trends.earth_test_user_credentials.json"),
#     "r",
# ) as fin:
#     regular_keys = json.load(fin)
# with open(
#     os.path.join(os.path.dirname(__file__), "trends.earth_admin_user_credentials.json"),
#     "r",
# ) as fin:
#     admin_keys = json.load(fin)


# Ensure any message boxes that open are closed within 1 second
def close_msg_boxes():
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QMessageBox):
            print("Closing message box")
            QTest.keyClick(w, Qt.Key_Enter)


timer = QTimer()
timer.timeout.connect(close_msg_boxes)
timer.start(1000)


# Class to store GEE tasks that have been submitted for processing and that
# have further tests to apply once the results have been returned. Queue stores
# tuples of (GEE Task ID, settings object)
# class GEETaskList:
#     def __init__(self):
#         self.tasks = {}
#
#     def put(self, task_id, status):
#         if self.tasks.has_key(task_id):
#             raise (Exception, "Task ID {} is already in task list".format(task_id))
#         self.tasks[task_id] = status
#
#     def get(self):
#         if task.is_finished():
#             return task
#         else:
#             # if the task isn't finished, add it back onto the queue (at the
#             # end, so another task will come up for consideration next time)
#             self.put(task)
#             return None
#
#     def update_status(self):
#         pass
#
#     def empty(self):
#         return True
#
#
# gee_queue = GEETaskList()
