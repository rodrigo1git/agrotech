"""SQLite transaccional: evidencia, estados y decisiones reversibles."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .observaciones import crear_observaciones, huella


def empaquetar(datos):
    return json.dumps(datos, ensure_ascii=False, sort_keys=True, allow_nan=False)


class Almacen:
    def __init__(self, ruta):
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(ruta)
        self.db.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
            INSERT OR IGNORE INTO schema_version VALUES(1);
            CREATE TABLE IF NOT EXISTS surveys(id TEXT PRIMARY KEY, payload TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS captures(survey_id TEXT NOT NULL REFERENCES surveys(id), image_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(survey_id,image_id));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES surveys(id), image_id TEXT NOT NULL, active INTEGER NOT NULL, payload TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(survey_id,image_id) WHERE active=1;
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES surveys(id), run_id TEXT NOT NULL REFERENCES runs(id), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trees(id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES surveys(id), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS groups_table(id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES surveys(id), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS derived_observations(id TEXT PRIMARY KEY REFERENCES observations(id), survey_id TEXT NOT NULL REFERENCES surveys(id), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS associations(survey_id TEXT NOT NULL, observation_id TEXT NOT NULL REFERENCES observations(id), entity_id TEXT NOT NULL, relation TEXT NOT NULL, PRIMARY KEY(survey_id,observation_id,entity_id,relation));
            CREATE TABLE IF NOT EXISTS overrides(survey_id TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(survey_id,kind,target));
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES surveys(id), event_type TEXT NOT NULL, generation INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def transaccion(self):
        if self._transaction_depth:
            yield
            return
        self._transaction_depth = 1
        try:
            with self.db:
                yield
        finally:
            self._transaction_depth = 0

    def survey(self, clave, config):
        fila = self.db.execute("SELECT payload FROM surveys WHERE id=?", (clave,)).fetchone()
        if fila is None:
            datos = {"id": clave, "config": config, "origin": None}
            with self.transaccion():
                self.db.execute("INSERT INTO surveys(id,payload) VALUES(?,?)", (clave, empaquetar(datos)))
            return datos
        return json.loads(fila[0])

    def guardar_survey(self, datos):
        with self.transaccion():
            self.db.execute("UPDATE surveys SET payload=? WHERE id=?", (empaquetar(datos), datos["id"]))

    def importar(self, survey_id, registro):
        """Activar una ejecución por imagen, de forma atómica e idempotente."""
        meta = registro.get("mapillary")
        if not isinstance(meta, dict) or not meta.get("id"):
            raise ValueError("Falta metadata Mapillary en el resultado")
        contenido = {k: registro.get(k) for k in ("model", "revision", "prompt", "threshold", "text_threshold", "preprocessing", "image_sha256", "width", "height", "detections", "mapillary")}
        if contenido["prompt"] != "tree.":
            raise ValueError("El inventario mantiene prompt='tree.'; importá ese experimento")
        run_id = huella({"survey": survey_id, "result": contenido})
        observaciones = crear_observaciones(registro, run_id, survey_id)
        image_id = str(meta["id"])
        with self.transaccion():
            fila = self.db.execute("SELECT id FROM runs WHERE survey_id=? AND image_id=? AND active=1", (survey_id, image_id)).fetchone()
            if fila and fila[0] == run_id:
                return False
            self.db.execute("INSERT INTO captures VALUES(?,?,?) ON CONFLICT(survey_id,image_id) DO UPDATE SET payload=excluded.payload", (survey_id, image_id, empaquetar(meta)))
            self.db.execute("UPDATE runs SET active=0 WHERE survey_id=? AND image_id=?", (survey_id, image_id))
            self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET active=1", (run_id, survey_id, image_id, 1, empaquetar(contenido)))
            for obs in observaciones:
                self.db.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?)", (obs["id"], survey_id, run_id, empaquetar(obs)))
            self.evento(survey_id, "import", {"image_id": image_id, "run_id": run_id, "observations": len(observaciones)})
        return True

    def evento(self, survey_id, tipo, datos):
        self.db.execute("UPDATE surveys SET generation=generation+1 WHERE id=?", (survey_id,))
        generation = self.db.execute("SELECT generation FROM surveys WHERE id=?", (survey_id,)).fetchone()[0]
        event_id = str(uuid.uuid4())
        self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (event_id, survey_id, tipo, generation, datetime.now(timezone.utc).isoformat(), empaquetar(datos)))
        return event_id

    def capturas(self, survey_id):
        return {fila[0]: json.loads(fila[1]) for fila in self.db.execute("SELECT image_id,payload FROM captures WHERE survey_id=? ORDER BY image_id", (survey_id,))}

    def observaciones(self, survey_id):
        return [json.loads(fila[0]) for fila in self.db.execute("SELECT o.payload FROM observations o JOIN runs r ON o.run_id=r.id WHERE o.survey_id=? AND r.active=1 ORDER BY o.id", (survey_id,))]

    def overrides(self, survey_id):
        return {(fila[0], fila[1]): json.loads(fila[2]) for fila in self.db.execute("SELECT kind,target,payload FROM overrides WHERE survey_id=?", (survey_id,))}

    def estado(self, survey_id):
        datos = {}
        for nombre, tabla in (("trees", "trees"), ("groups", "groups_table")):
            datos[nombre] = [json.loads(fila[0]) for fila in self.db.execute(f"SELECT payload FROM {tabla} WHERE survey_id=? ORDER BY id", (survey_id,))]
        datos["overrides"] = [{"kind": k, "target": t, "payload": p} for (k, t), p in sorted(self.overrides(survey_id).items())]
        datos["observations"] = [json.loads(fila[0]) for fila in self.db.execute("SELECT payload FROM derived_observations WHERE survey_id=? ORDER BY id", (survey_id,))]
        return datos

    def escribir_estado(self, survey_id, estado):
        self.db.execute("DELETE FROM derived_observations WHERE survey_id=?", (survey_id,))
        for obs in estado.get("observations", []):
            self.db.execute("INSERT INTO derived_observations VALUES(?,?,?)", (obs["id"], survey_id, empaquetar(obs)))
        for nombre, tabla in (("trees", "trees"), ("groups", "groups_table")):
            self.db.execute(f"DELETE FROM {tabla} WHERE survey_id=?", (survey_id,))
            for registro in estado[nombre]:
                self.db.execute(f"INSERT INTO {tabla} VALUES(?,?,?)", (registro["id"], survey_id, empaquetar(registro)))
        self.db.execute("DELETE FROM overrides WHERE survey_id=?", (survey_id,))
        for registro in estado.get("overrides", []):
            self.db.execute("INSERT INTO overrides VALUES(?,?,?,?)", (survey_id, registro["kind"], registro["target"], empaquetar(registro["payload"])))
        self.db.execute("DELETE FROM associations WHERE survey_id=?", (survey_id,))
        for tipo in ("trees", "groups"):
            for entidad in estado[tipo]:
                if not entidad.get("active", True):
                    continue
                for obs_id in entidad.get("observation_ids", []):
                    self.db.execute("INSERT INTO associations VALUES(?,?,?,?)", (survey_id, obs_id, entidad["id"], "individual_support" if tipo == "trees" else "group_evidence"))

    def guardar_estado(self, survey_id, estado, tipo="reconcile", detalle=None, journal=True):
        anterior = self.estado(survey_id)
        # Orden estable para que exportar/reconciliar sin cambios sea idempotente.
        for nombre in ("trees", "groups"):
            estado[nombre] = sorted(estado[nombre], key=lambda e: e["id"])
        estado["overrides"] = sorted(estado.get("overrides", []), key=lambda o: (o["kind"], o["target"]))
        estado["observations"] = sorted(estado.get("observations", []), key=lambda o: o["id"])
        if empaquetar(anterior) == empaquetar(estado):
            return None
        with self.transaccion():
            self.escribir_estado(survey_id, estado)
            return self.evento(survey_id, tipo, {"before": anterior, "after": estado, "detail": detalle or {}}) if journal else None

    def deshacer(self, survey_id, event_id):
        fila = self.db.execute("SELECT * FROM events WHERE id=? AND survey_id=?", (event_id, survey_id)).fetchone()
        if fila is None or fila["event_type"] not in ("split", "merge", "review", "anchor", "camera_override", "reconcile"):
            raise ValueError("El evento no corresponde a una corrección reversible")
        actual = self.db.execute("SELECT generation FROM surveys WHERE id=?", (survey_id,)).fetchone()[0]
        if actual != fila["generation"]:
            raise ValueError("Hubo cambios posteriores: revisá el estado actual antes de deshacer")
        anterior = json.loads(fila["payload"])["before"]
        with self.transaccion():
            self.escribir_estado(survey_id, anterior)
            return self.evento(survey_id, "undo", {"target_event": event_id})

    def eventos(self, survey_id):
        return [{**dict(fila), "payload": json.loads(fila["payload"])} for fila in self.db.execute("SELECT * FROM events WHERE survey_id=? ORDER BY generation", (survey_id,))]
