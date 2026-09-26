import os
import csv
import json
import tempfile
from datetime import datetime
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, flash
)
from database import (
    init_db, import_csv, get_all_prospects, get_prospect,
    get_signals, add_signal, get_analyses, get_dashboard_stats,
    mark_signal_read, dismiss_signal, get_action_items,
    update_action_status, get_db
)
from analyzer import (
    analyze_signal_with_ai, generate_sample_signals, SIGNAL_TYPES
)

app = Flask(__name__)
app.secret_key = os.urandom(24)

init_db()


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/dashboard")
def api_dashboard():
    stats = get_dashboard_stats()
    return jsonify(stats)


@app.route("/api/prospects")
def api_prospects():
    region = request.args.get("region")
    segment = request.args.get("segment")
    search = request.args.get("search")
    prospects = get_all_prospects(region=region, segment=segment, search=search)
    return jsonify(prospects)


@app.route("/api/prospects/<int:prospect_id>")
def api_prospect_detail(prospect_id):
    prospect = get_prospect(prospect_id)
    if not prospect:
        return jsonify({"error": "Prospect not found"}), 404

    signals = get_signals(prospect_id=prospect_id, limit=20)
    analyses = get_analyses(prospect_id=prospect_id, limit=10)
    actions = get_action_items(prospect_id=prospect_id)

    return jsonify({
        "prospect": prospect,
        "signals": signals,
        "analyses": analyses,
        "actions": actions,
    })


@app.route("/api/signals")
def api_signals():
    prospect_id = request.args.get("prospect_id", type=int)
    signal_type = request.args.get("type")
    limit = request.args.get("limit", 50, type=int)
    signals = get_signals(prospect_id=prospect_id, signal_type=signal_type, limit=limit)
    return jsonify(signals)


@app.route("/api/signals", methods=["POST"])
def api_add_signal():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    required = ["prospect_id", "signal_type", "headline"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    signal_id = add_signal(
        prospect_id=data["prospect_id"],
        signal_type=data["signal_type"],
        headline=data["headline"],
        summary=data.get("summary"),
        source=data.get("source"),
        source_url=data.get("source_url"),
        severity=data.get("severity", "medium"),
    )

    return jsonify({"signal_id": signal_id, "message": "Signal added"})


@app.route("/api/signals/<int:signal_id>/read", methods=["POST"])
def api_mark_read(signal_id):
    mark_signal_read(signal_id)
    return jsonify({"message": "Marked as read"})


@app.route("/api/signals/<int:signal_id>/dismiss", methods=["POST"])
def api_dismiss(signal_id):
    dismiss_signal(signal_id)
    return jsonify({"message": "Signal dismissed"})


@app.route("/api/signals/<int:signal_id>/analyze", methods=["POST"])
def api_analyze_signal(signal_id):
    conn = get_db()
    signal = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    conn.close()

    if not signal:
        return jsonify({"error": "Signal not found"}), 404

    signal = dict(signal)
    analysis_id = analyze_signal_with_ai(
        signal_id=signal_id,
        prospect_id=signal["prospect_id"],
        signal_type=signal["signal_type"],
        headline=signal["headline"],
        summary=signal.get("summary"),
    )

    if analysis_id:
        return jsonify({"analysis_id": analysis_id, "message": "Analysis complete"})
    return jsonify({"error": "Analysis failed"}), 500


@app.route("/api/analyses")
def api_analyses():
    prospect_id = request.args.get("prospect_id", type=int)
    limit = request.args.get("limit", 50, type=int)
    analyses = get_analyses(prospect_id=prospect_id, limit=limit)
    return jsonify(analyses)


@app.route("/api/actions")
def api_actions():
    status = request.args.get("status")
    prospect_id = request.args.get("prospect_id", type=int)
    actions = get_action_items(status=status, prospect_id=prospect_id)
    return jsonify(actions)


@app.route("/api/actions/<int:action_id>/status", methods=["POST"])
def api_update_action(action_id):
    data = request.get_json()
    if not data or "status" not in data:
        return jsonify({"error": "Status required"}), 400
    update_action_status(action_id, data["status"])
    return jsonify({"message": "Action updated"})


@app.route("/api/upload-csv", methods=["POST"])
def api_upload_csv():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "File must be a CSV"}), 400

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        imported, skipped = import_csv(tmp_path)
        return jsonify({
            "message": f"Imported {imported} prospects, skipped {skipped} duplicates",
            "imported": imported,
            "skipped": skipped,
        })
    finally:
        os.unlink(tmp_path)


@app.route("/api/generate-signals/<int:prospect_id>", methods=["POST"])
def api_generate_signals(prospect_id):
    signal_ids = generate_sample_signals(prospect_id)
    return jsonify({
        "message": f"Generated {len(signal_ids)} signals",
        "signal_ids": signal_ids,
    })


@app.route("/api/generate-all-signals", methods=["POST"])
def api_generate_all_signals():
    prospects = get_all_prospects()
    total = 0
    for p in prospects:
        signal_ids = generate_sample_signals(p["id"])
        total += len(signal_ids)
    return jsonify({"message": f"Generated {total} signals across {len(prospects)} prospects"})


@app.route("/api/analyze-all-pending", methods=["POST"])
def api_analyze_all_pending():
    conn = get_db()
    pending = conn.execute("""
        SELECT s.* FROM signals s
        LEFT JOIN analyses a ON s.id = a.signal_id
        WHERE a.id IS NULL AND s.is_dismissed = 0
        ORDER BY s.detected_at DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    analyzed = 0
    for signal in pending:
        signal = dict(signal)
        result = analyze_signal_with_ai(
            signal_id=signal["id"],
            prospect_id=signal["prospect_id"],
            signal_type=signal["signal_type"],
            headline=signal["headline"],
            summary=signal.get("summary"),
        )
        if result:
            analyzed += 1

    return jsonify({"message": f"Analyzed {analyzed} signals"})


@app.route("/api/signal-types")
def api_signal_types():
    return jsonify(SIGNAL_TYPES)


if __name__ == "__main__":
    csv_path = os.path.join(os.path.dirname(__file__), "prospects.csv")
    if os.path.exists(csv_path):
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
        conn.close()
        if count == 0:
            imported, skipped = import_csv(csv_path)
            print(f"Auto-imported {imported} prospects from prospects.csv")

    app.run(debug=True, port=5001)
