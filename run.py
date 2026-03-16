#!/usr/bin/env python3
import os
import sys

# Ensure the app directory is on the path and is the working directory
app_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(app_dir)
sys.path.insert(0, app_dir)

from app import app

port = int(os.environ.get("PORT", 3000))
app.run(debug=True, host="0.0.0.0", port=port, use_reloader=False)
