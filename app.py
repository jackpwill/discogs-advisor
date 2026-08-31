import os

from flask import Flask, jsonify, render_template
from dotenv import load_dotenv

from stats import build_stats
from advisor import generate_advisory, fallback_advisory, AdvisorError

load_dotenv()

app = Flask(__name__)

USERNAME = os.getenv("DISCOGS_USERNAME", "")


def _demo_mode():
    return os.getenv("ADVISOR_DEMO", "").lower() in ("1", "true", "yes", "on")


@app.route("/")
def index():
    """Compute the stats, ask the model to reason over them, render the report.

    The app owns every bit of presentation here: stats.py supplies the numbers,
    advisor.py supplies prose, and this template turns them into HTML. The model
    never emits markup of its own.
    """
    stats = build_stats(USERNAME)
    has_data = stats["collection"]["record_count"] > 0

    advisory = None
    advisory_error = None
    advisory_is_sample = False

    if has_data:
        # Use the live model when a key is present and demo mode is off.
        # Otherwise fall back to the deterministic offline advisory so the
        # report still renders in full -- clearly labeled as a sample.
        if _demo_mode() or not os.getenv("ANTHROPIC_API_KEY"):
            advisory = fallback_advisory(stats)
            advisory_is_sample = True
        else:
            try:
                advisory = generate_advisory(stats)
            except AdvisorError as e:
                advisory_error = str(e)
                advisory = fallback_advisory(stats)
                advisory_is_sample = True

    return render_template(
        "report.html",
        username=USERNAME,
        stats=stats["collection"],
        advisory=advisory,
        advisory_error=advisory_error,
        advisory_is_sample=advisory_is_sample,
        has_data=has_data,
    )


@app.route("/stats.json")
def stats_json():
    """The exact payload the model receives -- exposed for transparency."""
    return jsonify(build_stats(USERNAME))


if __name__ == "__main__":
    app.run(port=5002, debug=True)
