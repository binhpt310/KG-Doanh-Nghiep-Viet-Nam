from flask import Flask


app = Flask(__name__)


@app.after_request
def add_ngrok_skip_header(response):
    """Skip the ngrok interstitial when the app is exposed via tunnels."""
    response.headers["ngrok-skip-browser-warning"] = "skip"
    return response
