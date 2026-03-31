"""
Script de inicialización de la base de datos.
Crea todas las tablas y el usuario administrador por defecto.

Uso: python init_db.py
"""

from database import Base, engine, SessionLocal
from database import Usuario, RolUsuario, AlertaConfig, EtapaMaestro, AreaProduccion, EquipoProduccion, EtapaProducto
import bcrypt as _bcrypt
import sys
import json
import os

ETAPAS_MAESTRO_SEED = [
    {"id": 1, "nombre": "Blisteado"},
    {"id": 2, "nombre": "Compresion"},
    {"id": 3, "nombre": "Elaboracion"},
    {"id": 4, "nombre": "Estuchado"},
    {"id": 5, "nombre": "Etiquetado"},
    {"id": 6, "nombre": "Llenado"},
    {"id": 7, "nombre": "Revisado"},
]

AREAS_SEED = [
    {"id":  1, "etapa_id": 1, "nombre": "Area de Blisteado 1"},
    {"id":  2, "etapa_id": 1, "nombre": "Area de Blisteado 2"},
    {"id":  3, "etapa_id": 2, "nombre": "Area de Compresion 1"},
    {"id":  4, "etapa_id": 2, "nombre": "Area de Compresion 2"},
    {"id":  5, "etapa_id": 2, "nombre": "Area de Compresion 3"},
    {"id":  6, "etapa_id": 3, "nombre": "Area de Inyectables"},
    {"id":  7, "etapa_id": 3, "nombre": "Area de Liquidos Orales"},
    {"id":  8, "etapa_id": 3, "nombre": "Area de Ectoparasitarios"},
    {"id":  9, "etapa_id": 3, "nombre": "Area Betalactamicos"},
    {"id": 10, "etapa_id": 3, "nombre": "Area Mezcla y Granulacion"},
    {"id": 11, "etapa_id": 3, "nombre": "Area de Cremas"},
    {"id": 12, "etapa_id": 4, "nombre": "Area de Estuchado 1"},
    {"id": 13, "etapa_id": 4, "nombre": "Area de Estuchado 2"},
    {"id": 14, "etapa_id": 4, "nombre": "Area de Estuchado 3"},
    {"id": 15, "etapa_id": 5, "nombre": "Area de Etiquetado"},
    {"id": 16, "etapa_id": 6, "nombre": "Area Llenado Esteril"},
    {"id": 17, "etapa_id": 6, "nombre": "Area Llenado Liquidos Orales"},
    {"id": 18, "etapa_id": 6, "nombre": "Area Llenado Ectoparasitarios"},
    {"id": 19, "etapa_id": 7, "nombre": "Area de Revisado"},
    {"id": 20, "etapa_id": 6, "nombre": "Area Llenado de cremas"},
    {"id": 21, "etapa_id": 6, "nombre": "Area Llenado Betalactamicos"},
]

EQUIPOS_SEED = [
    {"id":  1, "area_id":  1, "nombre": "Blistera 1"},
    {"id":  2, "area_id":  2, "nombre": "Blistera 2"},
    {"id":  3, "area_id":  3, "nombre": "Comprimidora 1"},
    {"id":  4, "area_id":  4, "nombre": "Comprimidora 2"},
    {"id":  5, "area_id":  5, "nombre": "Comprimidora 3"},
    {"id":  6, "area_id":  9, "nombre": "Tambor rotatico"},
    {"id":  7, "area_id": 10, "nombre": "Granulador"},
    {"id":  8, "area_id": 10, "nombre": "Doble Cono"},
    {"id":  9, "area_id": 10, "nombre": "Molino calibrador"},
    {"id": 10, "area_id": 10, "nombre": "Lecho Fluido"},
    {"id": 11, "area_id": 11, "nombre": "Mezclador Cremas"},
    {"id": 12, "area_id":  8, "nombre": "Mezclador 1"},
    {"id": 13, "area_id":  8, "nombre": "Mezclador 2"},
    {"id": 17, "area_id": 15, "nombre": "Etiquetadora Semiautomatica"},
    {"id": 18, "area_id":  7, "nombre": "Tanque 1"},
    {"id": 19, "area_id":  7, "nombre": "Tanque 2"},
    {"id": 20, "area_id":  6, "nombre": "Reactor de 300 L"},
    {"id": 21, "area_id":  6, "nombre": "Reactor de 70 L"},
    {"id": 22, "area_id": 16, "nombre": "Bomba peristaltica"},
    {"id": 23, "area_id": 16, "nombre": "Tapadora Goteros"},
    {"id": 24, "area_id": 16, "nombre": "Tapadora Viales"},
    {"id": 25, "area_id": 17, "nombre": "Bomba peristaltica"},
    {"id": 26, "area_id": 17, "nombre": "Llenadora Semiautomatica"},
    {"id": 27, "area_id": 18, "nombre": "Bomba peristaltica"},
    {"id": 28, "area_id": 18, "nombre": "Llenadora de pomos"},
    {"id": 29, "area_id": 20, "nombre": "Llenadora Pomos Crema"},
]

ADMIN_EMAIL = "admin@sistema.com"
ADMIN_PASSWORD = "Admin123"
ADMIN_NOMBRE = "Administrador"

ALERTAS_DEFAULT = [
    {"nombre": "Orden próxima a vencer", "dias_limite": 7, "estado_aplica": "en_proceso"},
    {"nombre": "Orden sin movimiento", "dias_limite": 30, "estado_aplica": "pendiente"},
    {"nombre": "Entrega demorada", "dias_limite": 5, "estado_aplica": "terminada"},
]


def init():
    print("Creando tablas...")
    Base.metadata.create_all(bind=engine)
    print("  OK - tablas creadas.")

    db = SessionLocal()
    try:
        # Usuario admin
        existente = db.query(Usuario).filter(Usuario.email == ADMIN_EMAIL).first()
        if existente:
            print(f"  INFO - El usuario {ADMIN_EMAIL} ya existe, se omite.")
        else:
            admin = Usuario(
                nombre=ADMIN_NOMBRE,
                email=ADMIN_EMAIL,
                password_hash=_bcrypt.hashpw(ADMIN_PASSWORD.encode(), _bcrypt.gensalt()).decode(),
                rol=RolUsuario.admin,
                activo=True,
            )
            db.add(admin)
            db.commit()
            print(f"  OK - Usuario admin creado: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")

        # Alertas por defecto
        alertas_existentes = db.query(AlertaConfig).count()
        if alertas_existentes == 0:
            for a in ALERTAS_DEFAULT:
                db.add(AlertaConfig(**a, activo=True))
            db.commit()
            print(f"  OK - {len(ALERTAS_DEFAULT)} alertas por defecto creadas.")
        else:
            print(f"  INFO - Ya existen alertas configuradas, se omiten.")

        # Etapas maestro, áreas y equipos
        if db.query(EtapaMaestro).count() == 0:
            for e in ETAPAS_MAESTRO_SEED:
                db.add(EtapaMaestro(id=e["id"], nombre=e["nombre"], activo=True))
            db.flush()
            for a in AREAS_SEED:
                db.add(AreaProduccion(id=a["id"], etapa_id=a["etapa_id"], nombre=a["nombre"], activo=True))
            db.flush()
            for eq in EQUIPOS_SEED:
                db.add(EquipoProduccion(id=eq["id"], area_id=eq["area_id"], nombre=eq["nombre"], activo=True))
            db.commit()
            # Sincronizar secuencias en PostgreSQL
            from sqlalchemy import text
            for tabla in ("etapas_maestro", "areas_produccion", "equipos_produccion"):
                try:
                    db.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {tabla}), 1))"
                    ))
                    db.commit()
                except Exception:
                    db.rollback()
            print("  OK - Etapas maestro, áreas y equipos creados.")
        else:
            print("  INFO - Etapas maestro ya existen, se omiten.")

        # Etapas por producto (etapas_producto + etapa_producto_area)
        if db.query(EtapaProducto).count() == 0:
            seed_path = os.path.join(os.path.dirname(__file__), "etapas_producto_seed.json")
            if os.path.exists(seed_path):
                with open(seed_path, encoding="utf-8") as f:
                    seed = json.load(f)
                for row in seed["etapas_producto"]:
                    db.add(EtapaProducto(
                        id=row["id"], producto_id=row["producto_id"],
                        orden=row["orden"], nombre=row["nombre"],
                        activo=bool(row["activo"])
                    ))
                db.flush()
                from sqlalchemy import text
                for row in seed["etapa_producto_area"]:
                    db.execute(text(
                        "INSERT INTO etapa_producto_area (etapa_producto_id, area_produccion_id) "
                        "VALUES (:ep, :ap) ON CONFLICT DO NOTHING"
                    ), {"ep": row["etapa_producto_id"], "ap": row["area_produccion_id"]})
                db.commit()
                # Sincronizar secuencia
                try:
                    db.execute(text(
                        "SELECT setval(pg_get_serial_sequence('etapas_producto', 'id'), "
                        "COALESCE((SELECT MAX(id) FROM etapas_producto), 1))"
                    ))
                    db.commit()
                except Exception:
                    db.rollback()
                print(f"  OK - {len(seed['etapas_producto'])} etapas_producto cargadas.")
            else:
                print("  WARN - etapas_producto_seed.json no encontrado, se omite.")
        else:
            print("  INFO - etapas_producto ya existen, se omiten.")

        print("\nBase de datos inicializada correctamente.")

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    init()
