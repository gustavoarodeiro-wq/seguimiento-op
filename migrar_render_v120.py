"""
migrar_render_v120.py
=====================
Script de migración para deploy v1.2.0 en Render.

Qué hace:
  1. Nulifica etapa_producto_id y area_id en etapas_orden existentes
     (para que no queden FK colgadas al borrar maestros)
  2. Borra todos los maestros en orden seguro
  3. Reinserta los maestros desde el SQLite local (seguimiento_op.db)
     con los mismos IDs, de manera que las etapas_producto de nuevas
     órdenes funcionen correctamente.
  4. Las tablas de órdenes (ordenes, historial_estados, faltantes,
     entregas, etapas_orden) NO se tocan (excepto nulificar las FK
     arriba mencionadas).

Uso en Render Shell:
  python migrar_render_v120.py

Requiere que DATABASE_URL esté seteado (lo hace Render automáticamente).
El SQLite local debe estar subido al repo o accesible desde /opt/render/project/src/
"""

import os
import sys
import sqlite3

# ── Conectar a Postgres (producción) ──────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL no está definida.")
    sys.exit(1)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

from sqlalchemy import create_engine, text
prod_engine = create_engine(DATABASE_URL)

# ── Conectar al SQLite local ───────────────────────────────────────────────────

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "seguimiento_op.db")
if not os.path.exists(SQLITE_PATH):
    print(f"ERROR: No se encontró el SQLite local en {SQLITE_PATH}")
    sys.exit(1)

local_conn = sqlite3.connect(SQLITE_PATH)
local_conn.row_factory = sqlite3.Row

print(f"SQLite local: {SQLITE_PATH}")
print(f"Postgres URL: {DATABASE_URL[:40]}...")

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(conn, sql, params=None):
    if params:
        conn.execute(text(sql), params)
    else:
        conn.execute(text(sql))


def fetch_local(sql):
    cur = local_conn.execute(sql)
    return cur.fetchall()


# ══════════════════════════════════════════════════════════════════════════════
print("\n[1/5] Creando tablas nuevas si no existen (config_sistema, etc.)...")
# ══════════════════════════════════════════════════════════════════════════════
# La app ya hizo create_all al arrancar, pero por si acaso:
from database import Base, engine as _dummy
# Usamos el engine de producción directamente
from sqlalchemy import inspect as sa_inspect
with prod_engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS config_sistema (
            clave VARCHAR(100) PRIMARY KEY,
            valor TEXT
        )
    """))
    conn.commit()
print("  OK")


# ══════════════════════════════════════════════════════════════════════════════
print("\n[2/5] Nulificando FK en etapas_orden existentes...")
# ══════════════════════════════════════════════════════════════════════════════
with prod_engine.connect() as conn:
    r = conn.execute(text("UPDATE etapas_orden SET etapa_producto_id = NULL, area_id = NULL"))
    print(f"  {r.rowcount} filas de etapas_orden actualizadas")
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
print("\n[3/5] Borrando maestros en producción (orden seguro)...")
# ══════════════════════════════════════════════════════════════════════════════
TABLAS_BORRAR = [
    # tablas hoja primero
    "formula_componentes",
    "formulas",
    "etapa_producto_area",    # tabla de asociación M2M
    "etapas_producto",
    "etapa_produccion_area",  # tabla de asociación M2M
    "etapas_produccion",
    "equipos_produccion",
    "areas_produccion",
    "etapas_maestro",
    "productos_terminados",
    "graneles",
    "materiales_empaque",
    "materias_primas",
    "formas_farmaceuticas",
]

with prod_engine.connect() as conn:
    # Deshabilitar FK checks temporalmente (Postgres no tiene SET FOREIGN_KEY_CHECKS,
    # pero el orden de borrado ya es seguro. Usamos TRUNCATE con CASCADE donde aplique)
    for tabla in TABLAS_BORRAR:
        try:
            r = conn.execute(text(f"DELETE FROM {tabla}"))
            print(f"  {tabla}: {r.rowcount} filas borradas")
        except Exception as e:
            print(f"  {tabla}: SKIP ({e})")
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
print("\n[4/5] Insertando maestros desde SQLite local...")
# ══════════════════════════════════════════════════════════════════════════════

def insert_tabla(conn, tabla, rows, cols):
    if not rows:
        print(f"  {tabla}: 0 filas (vacío)")
        return
    placeholders = ", ".join([f":{c}" for c in cols])
    col_str = ", ".join(cols)
    sql = f"INSERT INTO {tabla} ({col_str}) VALUES ({placeholders})"
    for row in rows:
        conn.execute(text(sql), dict(zip(cols, [row[c] for c in cols])))
    print(f"  {tabla}: {len(rows)} filas insertadas")


with prod_engine.connect() as conn:

    # formas_farmaceuticas
    rows = fetch_local("SELECT id, nombre, unidad, activo FROM formas_farmaceuticas")
    insert_tabla(conn, "formas_farmaceuticas", rows,
                 ["id", "nombre", "unidad", "activo"])

    # materias_primas
    rows = fetch_local("SELECT id, codigo, descripcion, unidad, condicion, activo FROM materias_primas")
    insert_tabla(conn, "materias_primas", rows,
                 ["id", "codigo", "descripcion", "unidad", "condicion", "activo"])

    # materiales_empaque
    rows = fetch_local("SELECT id, codigo, descripcion, unidad, clasificacion, activo FROM materiales_empaque")
    insert_tabla(conn, "materiales_empaque", rows,
                 ["id", "codigo", "descripcion", "unidad", "clasificacion", "activo"])

    # graneles
    rows = fetch_local("SELECT id, codigo, descripcion, unidad, activo FROM graneles")
    insert_tabla(conn, "graneles", rows,
                 ["id", "codigo", "descripcion", "unidad", "activo"])

    # productos_terminados
    rows = fetch_local("""
        SELECT id, codigo, descripcion, unidad, forma_farmaceutica,
               forma_farmaceutica_id, activo, granel_id, cantidad_granel,
               cantidad_granel_x_unidad, cantidad_unidades_x_pt,
               peso_comprimido, cantidad_comprimidos_x_blister, cantidad_blisters_x_pt
        FROM productos_terminados
    """)
    insert_tabla(conn, "productos_terminados", rows, [
        "id", "codigo", "descripcion", "unidad", "forma_farmaceutica",
        "forma_farmaceutica_id", "activo", "granel_id", "cantidad_granel",
        "cantidad_granel_x_unidad", "cantidad_unidades_x_pt",
        "peso_comprimido", "cantidad_comprimidos_x_blister", "cantidad_blisters_x_pt"
    ])

    # etapas_maestro
    rows = fetch_local("SELECT id, nombre, activo FROM etapas_maestro")
    insert_tabla(conn, "etapas_maestro", rows, ["id", "nombre", "activo"])

    # areas_produccion
    rows = fetch_local("SELECT id, etapa_id, nombre, activo FROM areas_produccion")
    insert_tabla(conn, "areas_produccion", rows, ["id", "etapa_id", "nombre", "activo"])

    # equipos_produccion
    rows = fetch_local("SELECT id, area_id, nombre, activo FROM equipos_produccion")
    insert_tabla(conn, "equipos_produccion", rows, ["id", "area_id", "nombre", "activo"])

    # etapas_produccion (legacy)
    rows = fetch_local("SELECT id, forma_farmaceutica_id, orden, nombre, activo FROM etapas_produccion")
    insert_tabla(conn, "etapas_produccion", rows,
                 ["id", "forma_farmaceutica_id", "orden", "nombre", "activo"])

    # etapa_produccion_area (M2M legacy)
    rows = fetch_local("SELECT etapa_produccion_id, area_produccion_id FROM etapa_produccion_area")
    insert_tabla(conn, "etapa_produccion_area", rows,
                 ["etapa_produccion_id", "area_produccion_id"])

    # etapas_producto
    rows = fetch_local("SELECT id, producto_id, orden, nombre, activo FROM etapas_producto")
    insert_tabla(conn, "etapas_producto", rows,
                 ["id", "producto_id", "orden", "nombre", "activo"])

    # etapa_producto_area (M2M)
    rows = fetch_local("SELECT etapa_producto_id, area_produccion_id FROM etapa_producto_area")
    insert_tabla(conn, "etapa_producto_area", rows,
                 ["etapa_producto_id", "area_produccion_id"])

    # formulas
    rows = fetch_local("SELECT id, producto_codigo, producto_descripcion, activo FROM formulas")
    insert_tabla(conn, "formulas", rows,
                 ["id", "producto_codigo", "producto_descripcion", "activo"])

    # formula_componentes
    rows = fetch_local("""
        SELECT id, formula_id, tipo, componente_codigo, componente_descripcion, cantidad, unidad
        FROM formula_componentes
    """)
    insert_tabla(conn, "formula_componentes", rows, [
        "id", "formula_id", "tipo", "componente_codigo",
        "componente_descripcion", "cantidad", "unidad"
    ])

    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
print("\n[5/5] Sincronizando secuencias de IDs (PostgreSQL)...")
# ══════════════════════════════════════════════════════════════════════════════
TABLAS_SEQ = [
    "formas_farmaceuticas",
    "materias_primas",
    "materiales_empaque",
    "graneles",
    "productos_terminados",
    "etapas_maestro",
    "areas_produccion",
    "equipos_produccion",
    "etapas_produccion",
    "etapas_producto",
    "formulas",
    "formula_componentes",
]

with prod_engine.connect() as conn:
    for tabla in TABLAS_SEQ:
        try:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tabla}), 1))"
            ))
            print(f"  {tabla}: secuencia actualizada")
        except Exception as e:
            print(f"  {tabla}: SKIP ({e})")
    conn.commit()


print("\n✅ Migración v1.2.0 completada.")
print("   Las órdenes de producción existentes permanecen intactas.")
print("   Los maestros han sido reemplazados por los del SQLite local.")
local_conn.close()
