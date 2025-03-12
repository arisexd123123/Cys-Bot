from flask import Flask, render_template
from threading import Thread
import logging
import datetime
import os
import subprocess
import requests
import time
import json

app = Flask(__name__)
error_log = []
PERSISTENT_URL_FILE = "ngrok_url.json"

@app.route('/')
def home():
    return """
    <html>
        <head>
            <title>Discord Bot - Online</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    text-align: center;
                    margin-top: 50px;
                    background-color: #36393f;
                    color: white;
                }
                .container {
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #2f3136;
                    border-radius: 10px;
                    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                }
                h1 {
                    color: #7289da;
                }
                .status {
                    font-size: 24px;
                    margin: 20px 0;
                    color: #43b581;
                    font-weight: bold;
                }
                .error-log {
                    text-align: left;
                    background-color: #202225;
                    padding: 10px;
                    border-radius: 5px;
                    margin-top: 20px;
                    max-height: 300px;
                    overflow-y: auto;
                    color: #dcddde;
                }
                .error-entry {
                    margin-bottom: 10px;
                    border-bottom: 1px solid #40444b;
                    padding-bottom: 5px;
                }
                .timestamp {
                    color: #72767d;
                    font-size: 12px;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Discord Bot</h1>
                <div class="status">ONLINE</div>
                <p>The bot is currently running!</p>
                <p>For uptime monitoring, use: <code>/uptime</code></p>

                <div class="error-log">
                    <h3>Error Log:</h3>
                    """ + "".join([f'<div class="error-entry"><span class="timestamp">{entry["time"]}</span><br>{entry["error"]}</div>' for entry in error_log[-10:]]) + """
                </div>
            </div>
        </body>
    </html>
    """

@app.route('/uptime')
def uptime():
    """Dedicated endpoint for uptime monitoring services"""
    return "OK", 200

def run():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        log_error(f"Web server error: {e}")

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    print("Web server started!")

def log_error(error):
    """Log errors for debugging"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    error_entry = {
        "time": timestamp,
        "error": str(error)
    }
    error_log.append(error_entry)

    # Keep only the last 100 errors
    if len(error_log) > 100:
        error_log.pop(0)

    # Also print to console
    print(f"[ERROR {timestamp}] {error}")

def shutdown_server():
    """Function to shut down the Flask server"""
    try:
        import os
        import signal

        # Send a SIGINT to the server process
        os.kill(os.getpid(), signal.SIGINT)
        print("Web server shutting down...")
        return True
    except Exception as e:
        print(f"Failed to shut down server: {e}")
        return False

def get_ngrok_url():
    """Get or create ngrok URL for the server"""
    try:
        # ALWAYS kill any existing ngrok processes to force a new URL
        try:
            import os
            os.system("pkill -f ngrok")
            print("🔄 Killed existing ngrok processes")
            time.sleep(2)  # Give it time to fully terminate
        except Exception as e:
            print(f"Note: No existing ngrok processes to kill: {e}")

        # Delete any existing ngrok_url.json file to force a new URL
        try:
            if os.path.exists(PERSISTENT_URL_FILE):
                os.remove(PERSISTENT_URL_FILE)
                print("🔄 Removed existing ngrok URL file")
        except Exception as e:
            print(f"Error removing URL file: {e}")

        # Start ngrok if it's not running
        print("🔄 Starting ngrok tunnel...")

        # Get auth token from secrets
        import os
        ngrok_auth_token = os.environ.get("NGROK_AUTH_TOKEN")

        # First authenticate with ngrok if we have a token
        if ngrok_auth_token:
            try:
                print("🔑 Authenticating with ngrok...")
                auth_process = subprocess.Popen(
                    ["ngrok", "authtoken", ngrok_auth_token],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                auth_process.wait(timeout=10)
                print("✅ ngrok authentication complete")
            except Exception as auth_error:
                print(f"⚠️ ngrok authentication error: {auth_error}")
        else:
            print("⚠️ No NGROK_AUTH_TOKEN found in secrets. Free tier limitations will apply.")

        # Start ngrok tunnel with more robust options
        ngrok_process = subprocess.Popen(
            ["ngrok", "http", "8080", "--log=stdout"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )

        # Give it more time to start up
        time.sleep(5)

        # Try to get the URL again
        max_retries = 5
        for i in range(max_retries):
            try:
                response = requests.get("http://127.0.0.1:4040/api/tunnels")
                tunnels = response.json()["tunnels"]
                if tunnels:
                    url = tunnels[0]["public_url"]
                    print(f"✅ Created new ngrok tunnel: {url}")

                    # Save URL to persistent file with a timestamp to indicate it's fresh
                    with open(PERSISTENT_URL_FILE, 'w') as f:
                        json.dump({
                            "url": url,
                            "timestamp": time.time(),
                            "new_tunnel": True
                        }, f)

                    # Also update the ngrok_url.json file for compatibility
                    with open("ngrok_url.json", 'w') as f:
                        json.dump({
                            "url": url,
                            "timestamp": time.time()
                        }, f)

                    return url
            except Exception as e:
                if i < max_retries - 1:
                    print(f"⚠️ Retrying to get ngrok URL ({i+1}/{max_retries})...")
                    time.sleep(2)
                else:
                    print(f"❌ Failed to get ngrok URL: {e}")

        # If all retries fail, check if we have a saved URL
        if os.path.exists(PERSISTENT_URL_FILE):
            try:
                with open(PERSISTENT_URL_FILE, 'r') as f:
                    data = json.load(f)
                    url = data.get("url")
                    print(f"ℹ️ Using previously saved ngrok URL: {url}")
                    print("⚠️ This URL might be outdated if ngrok couldn't start")
                    return url
            except Exception as e:
                print(f"❌ Error reading persistent URL file: {e}")

        return None
    except Exception as e:
        print(f"❌ Error setting up ngrok: {e}")
        return None