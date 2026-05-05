import os
import sys
import subprocess

port = os.environ.get('PORT', '5000')

sys.exit(subprocess.call([
    'gunicorn',
    '--bind', f'0.0.0.0:{port}',
    '--workers', '1',
    '--timeout', '120',
    'app:app',
]))
