"""Central configuration. Override any value with an environment variable."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# MongoDB (operational / serving store)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "smart_parking")
USE_MOCK = os.getenv("USE_MOCK", "0") == "1"      # in-memory Mongo, for tests only

# Hive (batch analytics warehouse) - reached through `docker exec ... beeline`
HIVE_CONTAINER = os.getenv("HIVE_CONTAINER", "parking-hive")
HIVE_JDBC = os.getenv("HIVE_JDBC", "jdbc:hive2://localhost:10000/")
HIVE_DB = "smart_parking"

EXPORT_DIR = BASE_DIR / "hive_data"                # mounted at /data in the Hive container
MODEL_PATH = BASE_DIR / "models" / "parking_model.joblib"
HISTORY_DAYS = int(os.getenv("HISTORY_DAYS", "90"))

# Web app security
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "parking-demo-key")   # for IoT gateways POSTing /api/ingest
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")           # change this!

# Map (lots are placed around this point; override with MAP_LAT / MAP_LON)
MAP_CENTER = (float(os.getenv("MAP_LAT", "12.9716")), float(os.getenv("MAP_LON", "77.5946")))
