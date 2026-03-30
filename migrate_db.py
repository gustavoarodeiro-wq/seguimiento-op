"""
migrate_db.py
=============
Migraciones incrementales de esquema.
Se ejecuta al arrancar la app. Es idempotente: usa ADD COLUMN IF NOT EXISTS,
por lo que es seguro correrlo múltiples veces.
"""
from sqlalchemy import text


def run(engine):
    with engine.connect() as conn:

        # ── etapas_orden: todas las columnas del modelo actual ────────────────
        stmts = [
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS etapa_producto_id   INTEGER REFERENCES etapas_producto(id)",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS etapa_produccion_id INTEGER REFERENCES etapas_produccion(id)",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS area_id             INTEGER REFERENCES areas_produccion(id)",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS estado              VARCHAR(20) NOT NULL DEFAULT 'pendiente'",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS iteracion           INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS nombre_display      VARCHAR(200)",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS fecha_inicio        TIMESTAMP",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS fecha_fin           TIMESTAMP",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS cantidad_obtenida   FLOAT",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS unidad_obtenida     VARCHAR(10)",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS usuario_inicio_id   INTEGER REFERENCES usuarios(id)",
            "ALTER TABLE etapas_orden ADD COLUMN IF NOT EXISTS usuario_fin_id      INTEGER REFERENCES usuarios(id)",

            # ── formas_farmaceuticas: columna unidad agregada en v1.1 ─────────
            "ALTER TABLE formas_farmaceuticas ADD COLUMN IF NOT EXISTS unidad VARCHAR(5)",

            # ── productos_terminados: columnas de granel/comprimidos ───────────
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS granel_id                  INTEGER REFERENCES graneles(id)",
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS cantidad_granel             FLOAT",
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS cantidad_granel_x_unidad    FLOAT",
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS cantidad_unidades_x_pt      INTEGER",
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS peso_comprimido             FLOAT",
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS cantidad_comprimidos_x_blister INTEGER",
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS cantidad_blisters_x_pt      INTEGER",
            "ALTER TABLE productos_terminados ADD COLUMN IF NOT EXISTS forma_farmaceutica_id       INTEGER REFERENCES formas_farmaceuticas(id)",

            # ── usuarios: columna permisos_json ───────────────────────────────
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS permisos_json TEXT",

            # ── config_sistema: tabla nueva (create_all la crea, pero por si acaso) ──
            """
            CREATE TABLE IF NOT EXISTS config_sistema (
                clave VARCHAR(100) PRIMARY KEY,
                valor TEXT
            )
            """,
        ]

        for stmt in stmts:
            try:
                conn.execute(text(stmt.strip()))
            except Exception as e:
                # Loguear pero no frenar el arranque
                print(f"[migrate_db] warning: {e}")

        conn.commit()
        print("[migrate_db] Migraciones de esquema aplicadas correctamente.")
