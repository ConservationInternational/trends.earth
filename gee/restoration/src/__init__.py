__version__ =  "1.0.5"

import sys
import os
import rollbar

from gefcore import logger

rollbar.init(os.getenv('ROLLBAR_SCRIPT_TOKEN'), os.getenv('ENV'))

def rollbar_except_hook(exc_type, exc_value, traceback):
   # Report the issue to rollbar here.
   rollbar.report_exc_info((exc_type, exc_value, traceback))
   # display the error as normal here
   sys.__excepthook__(exc_type, exc_value, traceback)
