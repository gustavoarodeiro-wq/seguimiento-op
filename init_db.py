"""
Script de inicialización de la base de datos.
Crea todas las tablas y el usuario administrador por defecto.

Uso: python init_db.py
"""

from database import Base, engine, SessionLocal
from database import Usuario, RolUsuario, AlertaConfig
from passlib.context import CryptContext
import sys

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
                password_hash=pwd_context.hash(ADMIN_PASSWORD),
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

        print("\nBase de datos inicializada correctamente.")

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    init()
