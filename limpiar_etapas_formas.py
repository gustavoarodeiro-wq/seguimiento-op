"""
Elimina todas las etapas y areas de FormaFarmaceutica de la DB local.
Ya no tienen sentido porque las etapas y areas se gestionan a nivel de producto.

Uso: python limpiar_etapas_formas.py
"""
import os
os.environ.pop("DATABASE_URL", None)

from database import SessionLocal, engine
from sqlalchemy import text

db = SessionLocal()

# Primero borramos la tabla de relación etapa_produccion_area
res1 = db.execute(text("DELETE FROM etapa_produccion_area"))
# Luego las etapas
res2 = db.execute(text("DELETE FROM etapas_produccion"))

db.commit()
db.close()

print(f"✓ etapa_produccion_area: {res1.rowcount} registros eliminados")
print(f"✓ etapas_produccion:     {res2.rowcount} registros eliminados")
print("\nListo. La DB local está limpia.")
