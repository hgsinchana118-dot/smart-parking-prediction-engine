"""Flask API + dashboard for the Smart Parking Availability Prediction Engine."""
from datetime import datetime, timedelta

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import auth
import config
from auth import admin_required, login_required
from db import get_db
from ml import predict

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def _flag(name):
    return 1 if str(request.args.get(name, "0")).lower() in ("1", "true", "on", "yes") else 0


def _float(name, default=None):
    v = request.args.get(name)
    return default if v in (None, "") else float(v)


def _latest(lot_id):
    return get_db().readings.find_one({"lot_id": lot_id}, sort=[("ts", -1)])


@app.errorhandler(FileNotFoundError)
def _no_model(e):
    return jsonify(error=str(e)), 503


@app.errorhandler(KeyError)
def _not_found(e):
    return jsonify(error=str(e).strip("'\"")), 404


@app.errorhandler(ValueError)
def _bad(e):
    return jsonify(error=f"Invalid input: {e}"), 400


@app.errorhandler(RuntimeError)
def _runtime(e):
    return jsonify(error=str(e)), 500


# ---------------- pages & auth ----------------
@app.route("/")
@login_required
def index():
    return render_template("index.html", user=session["user"], role=session.get("role"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = auth.verify(request.form.get("username", "").strip(), request.form.get("password", ""))
        if u:
            session.clear()
            session["user"], session["role"] = u["username"], u["role"]
            return redirect(url_for("index"))
        error = "Invalid username or password"
    return render_template("login.html", mode="login", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        try:
            auth.create_user(request.form.get("username", "").strip(), request.form.get("password", ""), "user")
            return redirect(url_for("login"))
        except ValueError as e:
            error = str(e)
    return render_template("login.html", mode="register", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", user=session["user"])


@app.route("/api/health")
def health():  # public: used for uptime checks
    db = get_db()
    doc = db.analytics.find_one({}, {"engine": 1, "generated_at": 1})
    return jsonify(status="ok", readings=db.readings.count_documents({}),
                   analytics_engine=doc["engine"] if doc else None)


@app.route("/api/lots")
@login_required
def lots():
    db = get_db()
    out, tot_cap, tot_occ = [], 0, 0
    for lot in db.lots.find({}, {"_id": 0}).sort("lot_id", 1):
        cur = _latest(lot["lot_id"])
        if not cur:
            continue
        nxt_ts = cur["ts"] + timedelta(hours=1)
        _, pts = predict.predict_times(lot["lot_id"], [nxt_ts], temp_c=cur["temp_c"],
                                       rain_mm=cur["rain_mm"], event=cur["event"], holiday=cur["is_holiday"])
        nxt = pts[0]
        out.append({**lot, "ts": cur["ts"].isoformat(), "occupied": cur["occupied"],
                    "available": cur["available"], "occupancy": cur["occupancy_rate"],
                    "status": predict.status_for(cur["occupancy_rate"]),
                    "next_hour": {"available": nxt["available"], "occupancy": nxt["occupancy"],
                                  "status": nxt["status"]}})
        tot_cap += lot["capacity"]
        tot_occ += cur["occupied"]
    busiest = max(out, key=lambda l: l["occupancy"]) if out else None
    return jsonify(lots=out, summary={
        "capacity": tot_cap, "occupied": tot_occ, "available": tot_cap - tot_occ,
        "occupancy": round(tot_occ / tot_cap, 4) if tot_cap else 0,
        "busiest": busiest["name"] if busiest else None})


@app.route("/api/predict")
@login_required
def predict_api():
    lot_id = request.args.get("lot_id", "")
    ts = datetime.fromisoformat(request.args["datetime"]) if request.args.get("datetime") else datetime.now()
    lot, pts = predict.predict_times(lot_id, [ts], temp_c=_float("temp_c"), rain_mm=_float("rain_mm", 0.0),
                                     event=_flag("event"), holiday=_flag("holiday"))
    return jsonify(lot=lot, prediction=pts[0])


@app.route("/api/forecast/<lot_id>")
@login_required
def forecast_api(lot_id):
    cur = _latest(lot_id)
    if not cur:
        raise KeyError(f"Unknown lot_id {lot_id}")
    hours = max(1, min(int(request.args.get("hours", 12)), 48))
    start = cur["ts"] + timedelta(hours=1)
    return jsonify(predict.forecast(lot_id, start, hours, rain_mm=_float("rain_mm", 0.0),
                                    event=_flag("event"), holiday=_flag("holiday")))


@app.route("/api/ingest", methods=["POST"])
def ingest():
    """Accept a live sensor reading. Auth: admin session OR header X-API-Key (IoT gateways)."""
    if not (session.get("role") == "admin" or request.headers.get("X-API-Key") == config.INGEST_API_KEY):
        return jsonify(error="Admin login or valid X-API-Key required"), 401
    body = request.get_json(force=True, silent=True) or {}
    db = get_db()
    lot = db.lots.find_one({"lot_id": body.get("lot_id")}, {"_id": 0})
    if not lot:
        raise KeyError(f"Unknown lot_id {body.get('lot_id')}")
    occupied = int(body["occupied"])
    if not 0 <= occupied <= lot["capacity"]:
        raise ValueError(f"occupied must be between 0 and {lot['capacity']}")
    ts = datetime.fromisoformat(body["ts"]) if body.get("ts") else datetime.now().replace(minute=0, second=0, microsecond=0)
    doc = {"lot_id": lot["lot_id"], "lot_name": lot["name"], "lot_type": lot["type"], "ts": ts,
           "hour": ts.hour, "dow": ts.weekday(), "is_weekend": int(ts.weekday() >= 5),
           "is_holiday": int(body.get("is_holiday", 0)), "event": int(body.get("event", 0)),
           "temp_c": float(body.get("temp_c", predict.default_temp(ts.hour))),
           "rain_mm": float(body.get("rain_mm", 0.0)), "capacity": lot["capacity"],
           "occupied": occupied, "available": lot["capacity"] - occupied,
           "occupancy_rate": round(occupied / lot["capacity"], 4)}
    db.readings.insert_one(doc)
    return jsonify(status="stored", available=doc["available"]), 201


@app.route("/api/analytics/<name>")
@admin_required
def analytics(name):
    doc = get_db().analytics.find_one({"_id": name})
    if not doc:
        raise KeyError(f"No analytics '{name}'. Run: python pipeline.py analytics")
    rows = doc["rows"]
    if request.args.get("lot_id"):
        rows = [r for r in rows if r.get("lot_id") == request.args["lot_id"]]
    return jsonify(rows=rows, engine=doc["engine"], generated_at=doc["generated_at"].isoformat())


@app.route("/api/model")
@admin_required
def model_info():
    doc = get_db().model_metrics.find_one({"_id": "latest"}, {"_id": 0})
    if not doc:
        raise FileNotFoundError("Model not trained yet. Run: python pipeline.py train")
    doc["trained_at"] = doc["trained_at"].isoformat()
    return jsonify(doc)


# ---------------- admin API ----------------
@app.route("/api/admin/stats")
@admin_required
def admin_stats():
    db = get_db()
    m = db.model_metrics.find_one({"_id": "latest"}) or {}
    a = db.analytics.find_one({}, {"engine": 1, "generated_at": 1}) or {}
    return jsonify(users=db.users.count_documents({}), lots=db.lots.count_documents({}),
                   readings=db.readings.count_documents({}),
                   model_trained_at=m["trained_at"].isoformat() if m else None,
                   model_mae_spaces=m.get("mae_spaces"), analytics_engine=a.get("engine"),
                   analytics_at=a["generated_at"].isoformat() if a else None)


@app.route("/api/admin/users")
@admin_required
def admin_users():
    rows = [{"username": u["username"], "role": u["role"], "created_at": u["created_at"].isoformat()}
            for u in get_db().users.find().sort("created_at", 1)]
    return jsonify(users=rows)


@app.route("/api/admin/users/<username>", methods=["DELETE"])
@admin_required
def admin_delete_user(username):
    if username == session["user"]:
        return jsonify(error="You cannot delete your own account"), 400
    r = get_db().users.delete_one({"username": username})
    if not r.deleted_count:
        raise KeyError("User not found")
    return jsonify(status="deleted")


@app.route("/api/admin/users/<username>/role", methods=["PUT"])
@admin_required
def admin_user_role(username):
    role = (request.get_json(silent=True) or {}).get("role")
    if role not in ("user", "admin"):
        raise ValueError("role must be 'user' or 'admin'")
    if username == session["user"]:
        return jsonify(error="You cannot change your own role"), 400
    r = get_db().users.update_one({"username": username}, {"$set": {"role": role}})
    if not r.matched_count:
        raise KeyError("User not found")
    return jsonify(status="updated")


def _lot_fields(body, partial=False):
    out = {}
    if "name" in body or not partial:
        out["name"] = str(body["name"]).strip()
        if not out["name"]:
            raise ValueError("name is required")
    if "type" in body or not partial:
        out["type"] = str(body.get("type") or "public").strip()
    if "capacity" in body or not partial:
        out["capacity"] = int(body["capacity"])
        if out["capacity"] <= 0:
            raise ValueError("capacity must be positive")
    for k, lo, hi in (("lat", -90, 90), ("lon", -180, 180)):
        if k in body or not partial:
            out[k] = float(body[k])
            if not lo <= out[k] <= hi:
                raise ValueError(f"{k} out of range")
    return out


@app.route("/api/admin/lots", methods=["GET"])
@admin_required
def admin_list_lots():
    return jsonify(lots=list(get_db().lots.find({}, {"_id": 0}).sort("lot_id", 1)))


@app.route("/api/admin/lots", methods=["POST"])
@admin_required
def admin_add_lot():
    body = request.get_json(silent=True) or {}
    fields = _lot_fields(body)
    db = get_db()
    nums = [int(l["lot_id"][1:]) for l in db.lots.find({}, {"lot_id": 1}) if l["lot_id"][1:].isdigit()]
    lot_id = f"L{(max(nums) if nums else 0) + 1:02d}"
    db.lots.insert_one({"lot_id": lot_id, **fields})
    return jsonify(status="created", lot_id=lot_id), 201


@app.route("/api/admin/lots/<lot_id>", methods=["PUT"])
@admin_required
def admin_edit_lot(lot_id):
    fields = _lot_fields(request.get_json(silent=True) or {}, partial=True)
    r = get_db().lots.update_one({"lot_id": lot_id}, {"$set": fields})
    if not r.matched_count:
        raise KeyError(f"Unknown lot_id {lot_id}")
    return jsonify(status="updated")


@app.route("/api/admin/retrain", methods=["POST"])
@admin_required
def admin_retrain():
    from ml import train
    m = train.train()
    predict.load_model(force=True)
    return jsonify(status="trained", mae_spaces=m["mae_spaces"], r2=m["r2"])


@app.route("/api/admin/analytics", methods=["POST"])
@admin_required
def admin_analytics():
    from etl import analytics as an
    engine = (request.get_json(silent=True) or {}).get("engine", "pandas")
    if engine not in ("pandas", "hive"):
        raise ValueError("engine must be 'pandas' or 'hive'")
    return jsonify(status="done", engine=engine, tables=an.run(engine))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
