# Smart Parking Space Availability Prediction Engine
Advanced Big Data Analytics project - **MongoDB + Hive + ML + Flask dashboard**

## Architecture
```
 IoT sensors (simulated)            Batch layer                    Serving layer
 etl/simulator.py  ──►  MongoDB  ──► CSV export ──► Hive (ORC, partitioned by lot_type)
 POST /api/ingest        readings       │                    │  6 HiveQL analyses
                           ▲            │                    ▼
                           │            └────────────►  MongoDB `analytics`
                           │                                  │
                 ml/train.py (HistGradientBoosting)           ▼
                           │                        Flask API  ──►  Dashboard (Chart.js)
                           └── models/parking_model.joblib ──► /api/forecast, /api/predict
```
| Layer | Tech | Role |
|---|---|---|
| Ingestion | Flask `/api/ingest`, simulator | Live sensor readings |
| Operational store | MongoDB | readings, lots, analytics results, model metrics |
| Warehouse | Hive (ORC, partitioned) | Heavy aggregations: window functions, percentiles, CASE bucketing |
| ML | scikit-learn | Predicts occupancy -> free spaces for any lot/hour/weather |
| App | Flask + Chart.js | Live view, forecast, planner, analytics, model metrics |

## Setup (Windows PowerShell)
Keep the project folder **outside OneDrive** (e.g. `C:\projects\smart-parking-engine`) so Docker bind mounts and sync don't clash.

```powershell
cd C:\projects\smart-parking-engine
python -m venv venv
.\venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt

docker compose up -d                  # starts MongoDB + HiveServer2 (Hive needs ~1 min to boot)
python pipeline.py all                # generate -> Hive load -> Hive analytics -> train model
python app.py                         # open http://127.0.0.1:5000
```

### No Docker / Hive available?
Install MongoDB Community locally (or run only the `mongo` container: `docker compose up -d mongo`), then:
```powershell
python pipeline.py all --engine pandas   # same analytics, computed with pandas instead of Hive
```

### Smoke test (no MongoDB needed)
```powershell
python tests\smoke_test.py
```

## Login, roles and admin console
`python pipeline.py all` creates a default admin: **admin / admin123** (override with `ADMIN_USERNAME` / `ADMIN_PASSWORD`, or create one with
`python pipeline.py create-admin --username me --password S3cret!`). **Change the default password and set `SECRET_KEY` before any real deployment.**

| Role | Can do |
|---|---|
| Visitor | Register at `/register`; `/api/health` is public |
| User (driver view) | Live Overview, Map, Forecast & Planner only |
| Admin | Driver view + Big Data Analytics, Model Performance and `/admin`: edit/add lots (capacity, coordinates), manage users and roles, retrain the model, re-run analytics (pandas or Hive), store manual readings |

Passwords are hashed (Werkzeug). IoT gateways can post readings without a login by sending the header `X-API-Key: <INGEST_API_KEY>` (default `parking-demo-key`; override with the env var).

## Map view
The **Map** tab shows each lot as a circle coloured by live occupancy (Leaflet + OpenStreetMap tiles, needs internet). Simulated lots are placed around a default centre;
set your city with `$env:MAP_LAT="12.2958"; $env:MAP_LON="76.6394"` before `python pipeline.py generate`, or edit coordinates in the admin console.

## Using a real dataset
Download a real parking-occupancy CSV (e.g. the public **Birmingham parking** dataset from the UCI repository, columns `SystemCodeNumber, Capacity, Occupancy, LastUpdated`) and run:
```powershell
python pipeline.py load-real --csv C:\projects\data\birmingham.csv                  # + Hive load, analytics, training
python pipeline.py load-real --csv my.csv --lot-col lot --cap-col slots --occ-col used --ts-col time --engine pandas
```
Readings are averaged per lot per hour. Real feeds usually lack weather/event data, so those fields are neutral (rain 0, no event): the model learns time-of-day and
day-of-week patterns only, and the rain/event charts will be flat. Add a weather source later to restore them. The loader is covered by a test using a CSV in the Birmingham layout.

## Pipeline commands
| Command | What it does |
|---|---|
| `python pipeline.py generate` | Simulate 90 days x 10 lots hourly sensor data -> MongoDB |
| `python pipeline.py hive-load` | Export to CSV, create Hive tables, load + convert to ORC |
| `python pipeline.py analytics` | Run HiveQL analyses, save results into MongoDB |
| `python pipeline.py train` | Train and evaluate the model (14-day chronological holdout) |
| `python pipeline.py create-admin --username U --password P` | Create an admin account |
| `python pipeline.py load-real --csv FILE` | Replace simulated data with a real CSV, then Hive load + analytics + training |
| `python pipeline.py all` | generate -> Hive load -> analytics -> train (+ default admin) |

## HiveQL analyses (`etl/analytics.py`)
hourly occupancy profile · day x hour heatmap · weekday peak hours (`RANK() OVER`) · lot summary (`percentile_approx`, % hours near full) · rain impact · event impact

## REST API
All `/api/*` endpoints except `/api/health` need a login session; `/api/ingest` also accepts `X-API-Key`; `/api/admin/*` is admin-only.
| Endpoint | Description |
|---|---|
| `GET /api/lots` | Live status + next-hour prediction for every lot |
| `GET /api/forecast/<lot_id>?hours=12&rain_mm=0&event=0` | Hour-by-hour forecast + best arrival time |
| `GET /api/predict?lot_id=L01&datetime=2026-10-12T18:00&rain_mm=4&event=1` | What-if prediction |
| `POST /api/ingest` `{"lot_id":"L01","occupied":120}` | Store a sensor reading |
| `GET /api/analytics/<name>` | Hive results (`hourly_profile`, `dow_hour_heatmap`, `peak_hours`, `lot_summary`, `weather_impact`, `event_impact`) |
| `GET /api/model` | Accuracy metrics, per-lot error, feature importance |
| `/api/admin/...` | stats, users, lots (GET/POST/PUT), retrain, analytics |

## Using real data
Replace `etl/simulator.py` with a loader that writes documents of the same shape into `readings`
(`lot_id, ts, hour, dow, is_weekend, is_holiday, event, temp_c, rain_mm, capacity, occupied, available, occupancy_rate`)
and register your lots in `lots`. Everything downstream works unchanged.

## Troubleshooting
- `docker logs parking-hive` - HiveServer2 takes 30-90 s to start; `pipeline.py hive-load` waits up to 4 min.
- Port 27017 busy -> stop any local `mongod` service or change the port mapping.
- Hive `LOAD DATA` permission error -> make sure `hive_data\readings.csv` exists (run `generate` first).
