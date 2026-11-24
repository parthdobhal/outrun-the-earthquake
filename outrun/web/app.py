"""Flask application for Outrun the Earthquake (a simulation).

Routes:
    GET  /                    the browser interface
    GET  /api/health          health check
    GET  /api/world?seed=N    the simulated region for drawing (phones, towns)
    POST /api/run             one earthquake: simulation -> server -> evaluation
    POST /api/hidden-test     N hidden earthquakes the user cannot see
    GET  /api/false-alarms    false alerts per K, from simulated hours of noise
"""

from flask import Flask, jsonify, request, send_from_directory

from outrun import __version__
from outrun.web import api

SIMULATION_NOTICE = (
    "Simulation for learning. Not a real warning system and not Google's software."
)


def create_app(start_background_work: bool = False) -> Flask:
    """Build and return the Flask app (the 'application factory' pattern,
    so tests can create a fresh app each time).

    start_background_work=True starts measuring false alarms immediately;
    otherwise it starts on the first /api/false-alarms request."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    false_alarms = api.FalseAlarmCache()
    if start_background_work:
        false_alarms.start()
    app.config["FALSE_ALARMS"] = false_alarms

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify(
            status="ok",
            app="outrun-the-earthquake",
            version=__version__,
            simulation=True,
            notice=SIMULATION_NOTICE,
        )

    @app.get("/api/world")
    def world():
        try:
            seed = int(request.args.get("seed", 7))
        except ValueError:
            return jsonify(error="seed must be a whole number"), 400
        if not 0 <= seed <= api.MAX_SEED:
            return jsonify(error=f"seed must be between 0 and {api.MAX_SEED}"), 400
        return jsonify(api.world_payload(seed))

    @app.post("/api/run")
    def run():
        return _call(api.run_payload)

    @app.post("/api/hidden-test")
    def hidden_test():
        return _call(api.hidden_test_payload)

    @app.get("/api/false-alarms")
    def false_alarm_rates():
        cache = app.config["FALSE_ALARMS"]
        cache.start()
        return jsonify(cache.payload())

    def _call(function):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="send a JSON object"), 400
        try:
            return jsonify(function(data))
        except api.BadRequest as err:
            return jsonify(error=str(err)), 400

    return app


if __name__ == "__main__":
    # Development server only; bound to localhost.
    # Start measuring false alarms in the background straight away.
    create_app(start_background_work=True).run(host="127.0.0.1", port=5000, debug=False,
                                               threaded=True)
