"""
Copia las etapas y áreas definidas en cada FormaFarmaceutica
a todos los ProductoTerminado que tengan esa forma asignada.

Uso: python migrar_etapas_producto.py
"""
import os
os.environ.pop("DATABASE_URL", None)  # forzar SQLite local

from database import SessionLocal, ProductoTerminado, EtapaProduccion, EtapaProducto

db = SessionLocal()

productos = (
    db.query(ProductoTerminado)
    .filter(ProductoTerminado.forma_farmaceutica_id.isnot(None))
    .all()
)

copiados = 0
omitidos = 0
sin_etapas = 0

for producto in productos:
    # Si ya tiene etapas cargadas, no pisamos
    if producto.etapas:
        omitidos += 1
        continue

    etapas_forma = (
        db.query(EtapaProduccion)
        .filter(EtapaProduccion.forma_farmaceutica_id == producto.forma_farmaceutica_id)
        .order_by(EtapaProduccion.orden)
        .all()
    )

    if not etapas_forma:
        sin_etapas += 1
        continue

    for ep in etapas_forma:
        nueva = EtapaProducto(
            producto_id=producto.id,
            orden=ep.orden,
            nombre=ep.nombre,
            activo=ep.activo,
        )
        nueva.areas = list(ep.areas)  # copia las áreas asignadas
        db.add(nueva)
        copiados += 1

db.commit()
db.close()

print(f"✓ Etapas copiadas a productos: {copiados}")
print(f"  Productos ya tenían etapas (omitidos): {omitidos}")
print(f"  Productos sin etapas en su forma:      {sin_etapas}")
print(f"  Total productos procesados:            {len(productos)}")
