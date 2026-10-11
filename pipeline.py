"""Pipeline runner.   python pipeline.py all --engine hive|pandas"""
import argparse

import config
from db import get_db


def step_generate():
    from etl import simulator
    n = simulator.seed_database()
    print(f"[1/4] MongoDB: inserted {n:,} sensor readings ({config.HISTORY_DAYS} days, 10 lots)")


def step_hive_load():
    from etl import export, hive_client
    path, n = export.export_readings_csv()
    print(f"[2/4] Exported {n:,} rows -> {path}")
    print("      Waiting for HiveServer2 ...")
    hive_client.wait_until_ready()
    hive_client.run_script("/hive/01_schema.hql")
    hive_client.run_script("/hive/02_load.hql")
    print("      Hive: staging table loaded, ORC partitioned table populated")


def step_analytics(engine):
    from etl import analytics
    res = analytics.run(engine)
    print(f"[3/4] Analytics via {engine.upper()} -> MongoDB: {res}")


def step_admin(username=None, password=None):
    import auth
    if username:
        auth.create_user(username, password, "admin")
        print(f"Admin user '{username}' created")
    elif auth.ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD):
        print(f"Default admin created: {config.ADMIN_USERNAME} / {config.ADMIN_PASSWORD}  (change it!)")


def step_load_real(a):
    from etl import load_real_dataset
    n, lots = load_real_dataset.load(a.csv, a.lot_col, a.cap_col, a.occ_col, a.ts_col)
    print(f"Real dataset loaded: {n:,} hourly readings across {lots} lots")


def step_train():
    from ml import train
    m = train.train()
    print(f"[4/4] Model trained: MAE {m['mae_spaces']} spaces | R2 {m['r2']} | "
          f"baseline MAE {m['baseline_mae_spaces']} spaces")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["generate", "hive-load", "analytics", "train", "create-admin", "load-real", "all"])
    p.add_argument("--engine", choices=["hive", "pandas"], default="hive",
                   help="analytics engine (pandas = no Docker/Hive needed)")
    p.add_argument("--username"); p.add_argument("--password")
    p.add_argument("--csv"); p.add_argument("--lot-col", default="SystemCodeNumber")
    p.add_argument("--cap-col", default="Capacity"); p.add_argument("--occ-col", default="Occupancy")
    p.add_argument("--ts-col", default="LastUpdated")
    a = p.parse_args()
    if not config.USE_MOCK:
        get_db().command("ping")

    cmd = a.command
    if cmd == "create-admin":
        step_admin(a.username, a.password)
    if cmd == "load-real":
        if not a.csv:
            p.error("--csv is required for load-real")
        step_load_real(a)
        step_admin()
    if cmd in ("generate", "all"):
        step_generate()
        step_admin()
    full = cmd in ("all", "load-real")          # full = load -> Hive -> analytics -> train
    if (full or cmd == "hive-load") and a.engine == "hive":
        step_hive_load()
    if full or cmd == "analytics":
        step_analytics(a.engine)
    if full or cmd == "train":
        step_train()
    print("Done. Start the dashboard with: python app.py")
