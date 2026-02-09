import os

bind = f"0.0.0.0:{os.getenv('APP_PORT', '8080')}"
workers = 1
threads = 2
timeout = 300
accesslog = "-"
errorlog = "-"
