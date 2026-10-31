import os

bind = f"0.0.0.0:{os.environ.get('PORT', '3200')}"
workers = 1
threads = 1
timeout = 120
capture_output = True
errorlog = "-"
