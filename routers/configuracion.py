from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db, ConfigSistema
from routers.auth import require_auth
import config_cache

router = APIRouter()

CLAVES_PERMITIDAS = {
    "nombre_laboratorio",
    "zona_horaria",
    "venc_minimo_meses",
    "formato_hora",
}

def _exigir_admin(user: dict):
    if not user.get("permisos", {}).get("accion_admin"):
        raise HTTPException(status_code=403, detail="Se requiere rol administrador.")


@router.get("/api/config")
async def api_get_config(
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir_admin(user)
    rows = db.query(ConfigSistema).all()
    return {r.clave: r.valor or "" for r in rows}


@router.patch("/api/config")
async def api_set_config(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(require_auth),
):
    _exigir_admin(user)
    body = await request.json()
    saved = {}
    for clave, valor in body.items():
        if clave not in CLAVES_PERMITIDAS:
            continue
        valor = str(valor).strip() if valor is not None else ""
        row = db.query(ConfigSistema).filter(ConfigSistema.clave == clave).first()
        if row:
            row.valor = valor
        else:
            db.add(ConfigSistema(clave=clave, valor=valor))
        saved[clave] = valor
    db.commit()
    # Actualizar caché en memoria
    config_cache.set_all(saved)
    return {"ok": True, "saved": saved}


@router.get("/api/config/hora-actual")
async def api_hora_actual(user: dict = Depends(require_auth)):
    from config_cache import now_local
    ahora = now_local()
    return {"hora": ahora.strftime("%d/%m/%Y  %H:%M:%S")}
