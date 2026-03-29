"""
Migra las etapas únicas de EtapaProduccion (formas farmacéuticas) al maestro EtapaMaestro.
Uso: python migrar_etapas_maestro.py
"""
import os
os.environ.pop("DATABASE_URL", None)  # forzar SQLite local

from database import SessionLocal, EtapaProduccion, EtapaMaestro

db = SessionLocal()

etapas_existentes = db.query(EtapaProduccion).order_by(EtapaProduccion.nombre).all()
nombres_unicos = sorted(set(e.nombre.strip() for e in etapas_existentes if e.nombre))

creadas = 0
omitidas = 0

for nombre in nombres_unicos:
    existe = db.query(EtapaMaestro).filter(EtapaMaestro.nombre == nombre).first()
    if existe:
        omitidas += 1
    else:
        db.add(EtapaMaestro(nombre=nombre, activo=True))
        creadas += 1

db.commit()
db.close()

print(f"✓ Etapas creadas en el maestro: {creadas}")
print(f"  Omitidas (ya existían):        {omitidas}")
print(f"  Total etapas únicas:           {len(nombres_unicos)}")
