__version__ = "2.1.17"

import os
import sys

import rollbar

rollbar.init(os.getenv("ROLLBAR_SCRIPT_TOKEN"), os.getenv("ENV"))


def rollbar_except_hook(exc_type, exc_value, traceback):
    # Report the issue to rollbar here.
    rollbar.report_exc_info((exc_type, exc_value, traceback))
    # display the error as normal here
    sys.__excepthook__(exc_type, exc_value, traceback)


sys.excepthook = rollbar_except_hook
