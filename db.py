"""MongoDB connection helper (single shared client)."""
from functools import lru_cache

import config


@lru_cache(maxsize=1)
def get_db():
    if config.USE_MOCK:
        import mongomock
        return mongomock.MongoClient()[config.DB_NAME]
    from pymongo import MongoClient
    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=4000)
    return client[config.DB_NAME]


def ensure_indexes(db):
    db.readings.create_index([("lot_id", 1), ("ts", -1)])
    db.readings.create_index([("ts", 1)])
    db.lots.create_index("lot_id", unique=True)
