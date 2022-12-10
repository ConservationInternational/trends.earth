import qgis.gui
from qgis.core import Qgis
from qgis.PyQt import QtCore
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QEventLoop
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QThread
from qgis.PyQt.QtWidgets import QProgressBar
from qgis.PyQt.QtWidgets import QPushButton
from qgis.utils import iface

from .logger import log


class tr_worker:
    def tr(message):
        return QCoreApplication.translate("tr_worker", message)


class AbstractWorker(QtCore.QObject):
    """Abstract worker, inherit from this and implement the work method"""

    # available signals to be used in the concrete worker
    finished = QtCore.pyqtSignal(object)
    was_killed = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(Exception)
    progress = QtCore.pyqtSignal(float)
    toggle_show_progress = QtCore.pyqtSignal(bool)
    set_message = QtCore.pyqtSignal(str)
    toggle_show_cancel = QtCore.pyqtSignal(bool)

    # private signal, don't use in concrete workers this is automatically
    # emitted if the result is not None
    successfully_finished = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QObject.__init__(self)
        self.killed = False

    def run(self):
        try:
            result = self.work()
            self.finished.emit(result)
        except UserAbortedNotification:
            self.finished.emit(None)
        except Exception as e:
            # forward the exception upstream
            self.error.emit(e)
            self.finished.emit(None)

    def work(self):
        """Reimplement this putting your calculation here
        available are:
            self.progress.emit(0-100)
            self.killed
        :returns a python object - use None if killed is true
        """
        raise NotImplementedError

    def kill(self):
        self.killed = True
        self.set_message.emit("Aborting...")
        self.toggle_show_progress.emit(False)
        self.was_killed.emit(None)


class UserAbortedNotification(Exception):
    pass


def start_worker(worker, iface, message, with_progress=True):
    message_bar_item = qgis.gui.QgsMessageBar.createMessage(message)
    progress_bar = QProgressBar()
    progress_bar.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    if not with_progress:
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(0)
    cancel_button = QPushButton()
    cancel_button.setText("Cancel")
    cancel_button.clicked.connect(worker.kill)
    message_bar_item.layout().addWidget(progress_bar)
    message_bar_item.layout().addWidget(cancel_button)
    message_bar = iface.messageBar()
    message_bar.pushWidget(message_bar_item, Qgis.Info)

    # start the worker in a new thread
    # let Qt take ownership of the QThread
    thread = QThread(iface.mainWindow())
    worker.moveToThread(thread)

    worker.set_message.connect(
        lambda message: set_worker_message(message, message_bar_item)
    )
    worker.toggle_show_progress.connect(
        lambda show: toggle_worker_progress(show, progress_bar)
    )
    worker.toggle_show_cancel.connect(
        lambda show: toggle_worker_cancel(show, cancel_button)
    )
    worker.finished.connect(
        lambda result: worker_finished(result, thread, worker, iface, message_bar_item)
    )
    worker.error.connect(lambda e: worker_error(e, message))
    worker.was_killed.connect(
        lambda result: worker_killed(result, thread, worker, iface, message_bar_item)
    )

    def _set_progress_bar_value(value: float):
        progress_bar.setValue(int(value))

    worker.progress.connect(_set_progress_bar_value)
    thread.started.connect(worker.run)
    thread.start()

    return thread, message_bar_item


def worker_killed(result, thread, worker, iface, message_bar_item):
    pass


def worker_finished(result, thread, worker, iface, message_bar_item):
    message_bar = iface.messageBar()
    message_bar.popWidget(message_bar_item)
    if result is not None:
        worker.successfully_finished.emit(result)

    # clean up the worker and thread
    worker.deleteLater()
    thread.quit()
    thread.wait()
    thread.deleteLater()


def worker_error(e, message):
    log(f"Exception in worker thread ({message}): {e}")


def set_worker_message(message, message_bar_item):
    message_bar_item.setText(message)


def toggle_worker_progress(show_progress, progress_bar):
    progress_bar.setMinimum(0)
    if show_progress:
        progress_bar.setMaximum(100)
    else:
        # show an undefined progress
        progress_bar.setMaximum(0)


def toggle_worker_cancel(show_cancel, cancel_button):
    cancel_button.setVisible(show_cancel)


class StartWorker:
    def __init__(self, worker_class, process_name, *args):
        self.exception = None
        self.success = None
        self.return_val = None

        self.worker = worker_class(*args)

        pause = QEventLoop()
        self.worker.finished.connect(pause.quit)
        self.worker.successfully_finished.connect(self.save_success)
        self.worker.error.connect(self.save_exception)
        start_worker(
            self.worker, iface, tr_worker.tr("Processing: {}".format(process_name))
        )
        pause.exec_()

        if self.exception:
            raise self.exception

    def save_success(self, val=None):
        self.return_val = val
        self.success = True

    def get_return(self):
        return self.return_val

    def was_killed(self):
        return self.worker.killed

    def save_exception(self, exception):
        self.exception = exception

    def get_exception(self):
        return self.exception
