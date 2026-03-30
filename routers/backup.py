"""
Backup router — gestión de backups del SQLite.
Endpoints:
  GET  /backup                     → página HTML
  GET  /api/backup/config          → configuración actual
  PUT  /api/backup/config          → guardar configuración
  POST /api/backup                 → backup manual
  GET  /api/backup/list            → lista de archivos
  GET  /api/backup/download/{name} → descargar un archivo
  DELETE /api/backup/{name}        → eliminar un archivo
  POST /api/backup/restaurar/{name}→ restaurar un backup
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from shared import templates as _shared_templates
import os, json, sqlite3, threading, time
from datetime import datetime
from pathlib import Path

router = APIRouter()
templates = _shared_templates

# ── Rutas de configuración ─────────────────────────────────────────────────────

DB_PATH     = "seguimiento_op.db"
CONFIG_FILE = "backup_config.json"

_DEFAULT_CONFIG = {
    "ruta":         "",          # "" = misma carpeta que la DB
    "frecuencia":   "manual",    # manual | diario | semanal
    "hora":         "02:00",     # HH:MM
    "dia_semana":   1,           # 1=lunes … 7=domingo (solo para semanal)
    "retener":      10,          # cantidad máxima de backups a conservar
    "ultimo_backup": None,
}


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # rellenar claves faltantes con defaults
            for k, v in _DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(_DEFAULT_CONFIG)


def _save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _backup_dir(cfg: dict) -> Path:
    ruta = (cfg.get("ruta") or "").strip()
    if ruta:
        p = Path(ruta)
    else:
        p = Path(DB_PATH).parent / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Función principal de backup ────────────────────────────────────────────────

def hacer_backup(cfg: dict | None = None, etiqueta: str = "") -> str:
    """
    Realiza el backup usando la API nativa de SQLite.
    Devuelve el nombre del archivo creado.
    """
    if cfg is None:
        cfg = _load_config()

    directorio = _backup_dir(cfg)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"_{etiqueta}" if etiqueta else ""
    nombre = f"backup_{ts}{tag}.db"
    destino = directorio / nombre

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(str(destino))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Actualizar último backup
    cfg["ultimo_backup"] = datetime.now().isoformat()
    _save_config(cfg)

    # Aplicar retención
    _aplicar_retencion(directorio, cfg.get("retener", 10))

    return nombre


def _aplicar_retencion(directorio: Path, retener: int):
    """Elimina backups más viejos si supera la cantidad máxima."""
    archivos = sorted(
        [f for f in directorio.glob("backup_*.db")],
        key=lambda f: f.stat().st_mtime,
    )
    while len(archivos) > retener:
        archivos.pop(0).unlink(missing_ok=True)


# ── Scheduler en segundo plano ─────────────────────────────────────────────────

_scheduler_started = False
_scheduler_lock    = threading.Lock()


def _scheduler_loop():
    """Hilo que verifica cada 60 s si debe ejecutar un backup automático."""
    while True:
        try:
            cfg = _load_config()
            freq = cfg.get("frecuencia", "manual")
            if freq in ("diario", "semanal"):
                hora_str = cfg.get("hora", "02:00")
                ahora    = datetime.now()
                hh, mm   = map(int, hora_str.split(":"))

                en_hora = (ahora.hour == hh and ahora.minute == mm)

                if freq == "diario" and en_hora:
                    hacer_backup(cfg, etiqueta="auto")

                elif freq == "semanal" and en_hora:
                    dia_conf = int(cfg.get("dia_semana", 1))
                    # isoweekday: lunes=1 … domingo=7
                    if ahora.isoweekday() == dia_conf:
                        hacer_backup(cfg, etiqueta="auto")

        except Exception:
            pass

        time.sleep(60)


def start_scheduler():
    global _scheduler_started
    with _scheduler_lock:
        if not _scheduler_started:
            t = threading.Thread(target=_scheduler_loop, daemon=True)
            t.start()
            _scheduler_started = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_admin(request: Request):
    from routers.auth import get_current_user
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado.")
    if not user.get("permisos", {}).get("gestionar_usuarios"):
        raise HTTPException(status_code=403, detail="Sin permisos.")
    return user


def _archivo_info(f: Path) -> dict:
    stat = f.stat()
    return {
        "nombre":  f.name,
        "fecha":   datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "tamano":  stat.st_size,
        "tamano_mb": round(stat.st_size / 1_048_576, 2),
    }


# ── Rutas ─────────────────────────────────────────────────────────────────────

@router.post("/api/backup/elegir-carpeta")
async def api_elegir_carpeta(request: Request):
    """Abre el diálogo nativo de selección de carpeta del SO."""
    _auth_admin(request)
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        ruta = filedialog.askdirectory(title="Seleccionar carpeta de backups")
        root.destroy()
        if ruta:
            return {"ruta": ruta}
        return {"ruta": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el selector de carpeta: {e}")


@router.get("/backup")
async def page_backup(request: Request):
    user = _auth_admin(request)
    return templates.TemplateResponse(request, "backup.html", {"user": user})


@router.get("/api/backup/config")
async def api_get_config(request: Request):
    _auth_admin(request)
    return _load_config()


@router.put("/api/backup/config")
async def api_put_config(request: Request):
    _auth_admin(request)
    body = await request.json()
    cfg  = _load_config()

    if "ruta" in body:
        cfg["ruta"] = str(body["ruta"]).strip()
    if "frecuencia" in body and body["frecuencia"] in ("manual", "diario", "semanal"):
        cfg["frecuencia"] = body["frecuencia"]
    if "hora" in body:
        cfg["hora"] = str(body["hora"])
    if "dia_semana" in body:
        cfg["dia_semana"] = int(body["dia_semana"])
    if "retener" in body:
        cfg["retener"] = max(1, min(100, int(body["retener"])))

    # Validar ruta si se especificó
    ruta = cfg.get("ruta", "").strip()
    if ruta:
        try:
            Path(ruta).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Ruta inválida: {e}")

    _save_config(cfg)
    return cfg


@router.post("/api/backup")
async def api_hacer_backup(request: Request):
    _auth_admin(request)
    cfg    = _load_config()
    nombre = hacer_backup(cfg, etiqueta="manual")
    return {"ok": True, "nombre": nombre}


@router.get("/api/backup/list")
async def api_list(request: Request):
    _auth_admin(request)
    cfg       = _load_config()
    directorio = _backup_dir(cfg)
    archivos  = sorted(
        [f for f in directorio.glob("backup_*.db")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return [_archivo_info(f) for f in archivos]


@router.get("/api/backup/download/{nombre}")
async def api_download(nombre: str, request: Request):
    _auth_admin(request)
    cfg = _load_config()
    ruta = _backup_dir(cfg) / nombre
    if not ruta.exists() or not ruta.name.startswith("backup_"):
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    return FileResponse(
        path=str(ruta),
        filename=nombre,
        media_type="application/octet-stream",
    )


@router.delete("/api/backup/{nombre}")
async def api_delete(nombre: str, request: Request):
    _auth_admin(request)
    cfg  = _load_config()
    ruta = _backup_dir(cfg) / nombre
    if not ruta.exists() or not ruta.name.startswith("backup_"):
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    ruta.unlink()
    return {"ok": True}


@router.post("/api/backup/restaurar/{nombre}")
async def api_restaurar(nombre: str, request: Request):
    """
    Restaura un backup:
    1. Hace un backup de seguridad de la DB actual con etiqueta 'pre_restauracion'
    2. Sobreescribe la DB actual con el backup seleccionado
    """
    _auth_admin(request)
    cfg  = _load_config()
    ruta = _backup_dir(cfg) / nombre
    if not ruta.exists() or not ruta.name.startswith("backup_"):
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")

    # Backup de seguridad antes de restaurar
    hacer_backup(cfg, etiqueta="pre_restauracion")

    # Restaurar: copiar el backup sobre la DB activa
    src = sqlite3.connect(str(ruta))
    dst = sqlite3.connect(DB_PATH)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    return {"ok": True, "mensaje": "Base de datos restaurada. Reiniciá la aplicación para reflejar los cambios."}
