import qgis.gui
from qgis.core import Qgis
from qgis.PyQt import QtCore
from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, Qt, QThread, QTimer
from qgis.PyQt.QtWidgets import QProgressBar, QPushButton
from qgis.utils import iface

from .logger import log

# If a worker goes this long without emitting ``progress`` or
# ``set_message``, the event loop is considered stalled and will be
# terminated.  As long as the worker keeps reporting activity the
# countdown resets, so genuinely long-running jobs are never killed.
_WORKER_INACTIVITY_TIMEOUT_MS = 120 * 60 * 1000  # 120 minutes

# If a download goes this long without receiving any bytes the event
# loop is considered stalled and will be terminated.
_DOWNLOAD_INACTIVITY_TIMEOUT_MS = 30 * 60 * 1000  # 30 minutes


class _WatchdogTimer(QtCore.QObject):
    """Inactivity watchdog: fires *on_timeout* if :meth:`kick` is not
    called within *timeout_ms* milliseconds.

    Connect any "progress" or "heartbeat" signal to :meth:`kick` so the
    countdown resets whenever the monitored operation shows signs of life.

    Example::

        watchdog = _WatchdogTimer(10_000, loop.quit)
        some_signal.connect(watchdog.kick)
        watchdog.start()
        loop.exec_()
        watchdog.stop()
    """

    def __init__(self, timeout_ms: int, on_timeout, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(on_timeout)

    def start(self):
        """Start (or restart) the countdown."""
        self._timer.start()

    def stop(self):
        """Stop the watchdog without firing."""
        self._timer.stop()

    def kick(self, *_args, **_kwargs):
        """Reset the countdown.

        Accepts arbitrary positional/keyword arguments so it can be
        connected directly to any Qt signal.
        """
        if self._timer.isActive():
            self._timer.start()  # restart resets the interval


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
    # Clean up the thread properly when worker is killed to prevent access violations
    # from marshmallow schema operations being interrupted
    message_bar = iface.messageBar()
    _pop_message_bar_widget(message_bar, message_bar_item)

    # clean up the worker and thread
    worker.deleteLater()
    thread.quit()
    thread.wait()
    thread.deleteLater()


def _pop_message_bar_widget(message_bar, widget):
    """Thread-safe wrapper around message_bar.popWidget(widget)."""
    if QtCore.QThread.currentThread() == QtCore.QCoreApplication.instance().thread():
        message_bar.popWidget(widget)
    else:
        QtCore.QTimer.singleShot(0, lambda: message_bar.popWidget(widget))


def worker_finished(result, thread, worker, iface, message_bar_item):
    message_bar = iface.messageBar()
    _pop_message_bar_widget(message_bar, message_bar_item)

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

        # Inactivity watchdog: resets every time the worker reports any
        # progress or status message.  Only fires if the worker goes
        # completely silent for _WORKER_INACTIVITY_TIMEOUT_MS.
        def _on_watchdog():
            log(
                "Worker inactivity timeout reached "
                f"({_WORKER_INACTIVITY_TIMEOUT_MS / 1000:.0f}s without "
                "any progress signal) — exiting event loop"
            )
            pause.quit()

        watchdog = _WatchdogTimer(_WORKER_INACTIVITY_TIMEOUT_MS, _on_watchdog)
        self.worker.progress.connect(watchdog.kick)
        self.worker.set_message.connect(watchdog.kick)

        start_worker(
            self.worker, iface, tr_worker.tr("Processing: {}".format(process_name))
        )
        watchdog.start()
        pause.exec_()
        watchdog.stop()

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
