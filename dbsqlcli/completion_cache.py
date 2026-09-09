# Disk cache of completion metadata (catalogs / schemas / tables), so
# suggestions work immediately at startup from the previous session's data
# while the background refresher fetches a fresh copy.
import json
import logging
import os
import tempfile

LOGGER = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.dbsqlcli/cache")
VERSION = 1


def _path(hostname, catalog):
    safe = "__".join([hostname or "host", catalog or "nocatalog"])
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in safe)
    return os.path.join(CACHE_DIR, safe + ".completions.json")


def dump(completer):
    """Serializable payload of a refreshed completer's metadata."""
    return {
        "version": VERSION,
        "dbname": completer.dbname,
        "databases": list(completer.databases),
        "catalogs": list(completer.catalogs),
        "namespaces": [
            [cat, schema, tables]
            for (cat, schema), tables in completer.namespace_tables.items()
        ],
        "tables": completer.dbmetadata["tables"],
        "views": completer.dbmetadata["views"],
    }


def apply(completer, payload):
    """Rehydrate a completer from a cached payload."""
    completer.set_dbname(payload.get("dbname", ""))
    completer.extend_database_names(payload.get("databases", []))
    completer.extend_catalog_names(payload.get("catalogs", []))

    ns = {}
    for cat, schema, tables in payload.get("namespaces", []):
        ns[(cat, schema)] = tables
    completer.namespace_tables = ns
    cat_schemas = {}
    for cat, schema in ns:
        cat_schemas.setdefault(cat, set()).add(schema)
    completer.catalog_schemas = {c: sorted(s) for c, s in cat_schemas.items()}

    for kind in ("tables", "views"):
        data = payload.get(kind, {})
        completer.dbmetadata[kind].update(data)
        for schema, rels in data.items():
            completer.all_completions.add(schema)
            completer.all_completions.update(rels.keys())
    for schemas in completer.catalog_schemas.values():
        completer.all_completions.update(schemas)


def load(hostname, catalog):
    """Cached payload for this connection, or None."""
    try:
        with open(_path(hostname, catalog)) as f:
            payload = json.load(f)
        if payload.get("version") != VERSION:
            return None
        return payload
    except Exception:
        return None


def save(hostname, catalog, payload):
    """Atomically persist the payload (best-effort)."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, _path(hostname, catalog))
    except Exception as e:
        LOGGER.warning("completion cache save failed: %s", e)
