from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Date, Text, Enum, ForeignKey, Table
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

def _now_ar():
    try:
        from config_cache import now_local
        return now_local()
    except Exception:
        return datetime.now()
import enum
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./seguimiento_op.db")

# Railway usa el prefijo postgres://, SQLAlchemy necesita postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Enums ──────────────────────────────────────────────────────────────────────

class RolUsuario(str, enum.Enum):
    admin = "admin"
    supervisor = "supervisor"
    operador = "operador"
    observador = "observador"

class UnidadMedida(str, enum.Enum):
    UN = "UN"
    KG = "KG"
    L = "L"
    G = "G"
    ML = "ML"

class TipoFaltante(str, enum.Enum):
    MP = "MP"
    ME = "ME"

class EstadoOrden(str, enum.Enum):
    pendiente = "pendiente"
    en_proceso = "en_proceso"
    terminada = "terminada"
    entregada = "entregada"
    cancelada = "cancelada"


# ── Modelos ───────────────────────────────────────────────────────────────────

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    rol = Column(Enum(RolUsuario), nullable=False, default=RolUsuario.operador)
    activo = Column(Boolean, default=True, nullable=False)
    permisos_json = Column(Text, nullable=True)  # JSON con overrides por usuario


class FormaFarmaceutica(Base):
    __tablename__ = "formas_farmaceuticas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    unidad = Column(String(5), nullable=True)  # 'G' or 'ML'
    activo = Column(Boolean, default=True, nullable=False)

    etapas = relationship("EtapaProduccion", back_populates="forma_farmaceutica")


etapa_produccion_area = Table(
    "etapa_produccion_area",
    Base.metadata,
    Column("etapa_produccion_id", Integer, ForeignKey("etapas_produccion.id"), primary_key=True),
    Column("area_produccion_id",  Integer, ForeignKey("areas_produccion.id"),  primary_key=True),
)

etapa_producto_area = Table(
    "etapa_producto_area",
    Base.metadata,
    Column("etapa_producto_id",  Integer, ForeignKey("etapas_producto.id"),     primary_key=True),
    Column("area_produccion_id", Integer, ForeignKey("areas_produccion.id"),    primary_key=True),
)


class EtapaProduccion(Base):
    __tablename__ = "etapas_produccion"

    id = Column(Integer, primary_key=True, index=True)
    forma_farmaceutica_id = Column(Integer, ForeignKey("formas_farmaceuticas.id"), nullable=False)
    orden = Column(Integer, nullable=False)
    nombre = Column(String(150), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    forma_farmaceutica = relationship("FormaFarmaceutica", back_populates="etapas")
    areas = relationship("AreaProduccion", secondary=etapa_produccion_area)


class EtapaProducto(Base):
    __tablename__ = "etapas_producto"

    id = Column(Integer, primary_key=True, index=True)
    producto_id = Column(Integer, ForeignKey("productos_terminados.id"), nullable=False)
    orden = Column(Integer, nullable=False)
    nombre = Column(String(150), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    producto = relationship("ProductoTerminado", back_populates="etapas")
    areas = relationship("AreaProduccion", secondary=etapa_producto_area)


class Granel(Base):
    __tablename__ = "graneles"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    descripcion = Column(String(255), nullable=False)
    unidad = Column(Enum(UnidadMedida), nullable=False, default=UnidadMedida.KG)
    activo = Column(Boolean, default=True, nullable=False)

    productos = relationship("ProductoTerminado", back_populates="granel")


class ProductoTerminado(Base):
    __tablename__ = "productos_terminados"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    descripcion = Column(String(255), nullable=False)
    unidad = Column(Enum(UnidadMedida), nullable=False, default=UnidadMedida.UN)
    forma_farmaceutica = Column(String(100), nullable=True)
    forma_farmaceutica_id = Column(Integer, ForeignKey("formas_farmaceuticas.id"), nullable=True)
    activo = Column(Boolean, default=True, nullable=False)
    granel_id = Column(Integer, ForeignKey("graneles.id"), nullable=True)
    cantidad_granel = Column(Float, nullable=True)
    cantidad_granel_x_unidad = Column(Float, nullable=True)   # granel por unidad (1 decimal)
    cantidad_unidades_x_pt   = Column(Integer, nullable=True) # unidades por PT, default 1
    peso_comprimido          = Column(Float, nullable=True)   # g por comprimido
    cantidad_comprimidos_x_blister = Column(Integer, nullable=True)
    cantidad_blisters_x_pt         = Column(Integer, nullable=True)

    granel = relationship("Granel", back_populates="productos")
    forma_farmaceutica_obj = relationship("FormaFarmaceutica")
    etapas = relationship("EtapaProducto", back_populates="producto", cascade="all, delete-orphan")


class MateriaPrima(Base):
    __tablename__ = "materias_primas"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    descripcion = Column(String(255), nullable=False)
    unidad = Column(Enum(UnidadMedida), nullable=False, default=UnidadMedida.KG)
    condicion = Column(String(20), nullable=True)  # 'Activo' | 'Excipiente'
    activo = Column(Boolean, default=True, nullable=False)


class MaterialEmpaque(Base):
    __tablename__ = "materiales_empaque"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    descripcion = Column(String(255), nullable=False)
    unidad = Column(Enum(UnidadMedida), nullable=False, default=UnidadMedida.UN)
    clasificacion = Column(String(100), nullable=True)
    activo = Column(Boolean, default=True, nullable=False)


class Orden(Base):
    __tablename__ = "ordenes"

    id = Column(Integer, primary_key=True, index=True)
    fecha_carga = Column(DateTime, default=_now_ar, nullable=False)
    codigo_producto = Column(String(50), nullable=False)
    descripcion_producto = Column(String(255), nullable=False)
    lote_granel = Column(String(50), nullable=True)
    lote_pt = Column(String(50), nullable=True)
    op = Column(String(50), nullable=True, index=True)
    fecha_vencimiento = Column(Date, nullable=True)
    cantidad = Column(Float, nullable=False)
    unidad = Column(Enum(UnidadMedida), nullable=False, default=UnidadMedida.UN)
    estado = Column(String(50), nullable=False, default="revisar")
    subestado = Column(String(100), nullable=True)
    fecha_inicio_produccion = Column(DateTime, nullable=True)
    fecha_terminado = Column(DateTime, nullable=True)
    cantidad_obtenida = Column(Float, nullable=True)
    muestras_control = Column(Float, nullable=True)
    rendimiento = Column(Float, nullable=True)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    ultima_modificacion_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    ultima_modificacion_fecha = Column(DateTime, nullable=True)

    historial = relationship("HistorialEstado", back_populates="orden")
    faltantes = relationship("Faltante", back_populates="orden")
    entregas = relationship("Entrega", back_populates="orden")
    etapas_orden = relationship("EtapaOrden", back_populates="orden", cascade="all, delete-orphan")


class HistorialEstado(Base):
    __tablename__ = "historial_estados"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    estado_anterior = Column(String(50), nullable=True)
    estado_nuevo = Column(String(50), nullable=False)
    subestado_anterior = Column(String(100), nullable=True)
    subestado_nuevo = Column(String(100), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha = Column(DateTime, default=_now_ar, nullable=False)
    observaciones = Column(Text, nullable=True)

    orden = relationship("Orden", back_populates="historial")


class Faltante(Base):
    __tablename__ = "faltantes"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    tipo = Column(Enum(TipoFaltante), nullable=False)
    item_id = Column(Integer, nullable=True)
    codigo = Column(String(50), nullable=False)
    descripcion = Column(String(255), nullable=False)
    observacion = Column(Text, nullable=True)
    resuelto = Column(Boolean, default=False, nullable=False)
    fecha_registro = Column(DateTime, default=_now_ar, nullable=False)
    fecha_resolucion = Column(DateTime, nullable=True)

    orden = relationship("Orden", back_populates="faltantes")


class Entrega(Base):
    __tablename__ = "entregas"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    fecha_entrega = Column(DateTime, default=_now_ar, nullable=False)
    cantidad_entregada = Column(Float, nullable=False)
    muestras_control = Column(Float, nullable=True)
    remito = Column(String(100), nullable=True)
    es_entrega_final = Column(Boolean, default=False, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    orden = relationship("Orden", back_populates="entregas")


class Formula(Base):
    __tablename__ = "formulas"

    id = Column(Integer, primary_key=True, index=True)
    producto_codigo = Column(String(50), nullable=False, unique=True, index=True)
    producto_descripcion = Column(String(255), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    componentes = relationship("FormulaComponente", back_populates="formula", cascade="all, delete-orphan")


class FormulaComponente(Base):
    __tablename__ = "formula_componentes"

    id = Column(Integer, primary_key=True, index=True)
    formula_id = Column(Integer, ForeignKey("formulas.id"), nullable=False)
    tipo = Column(Enum(TipoFaltante), nullable=False)   # MP | ME
    componente_codigo = Column(String(50), nullable=False)
    componente_descripcion = Column(String(255), nullable=False)
    cantidad = Column(Float, nullable=False)
    unidad = Column(String(10), nullable=False)

    formula = relationship("Formula", back_populates="componentes")


class EtapaOrden(Base):
    __tablename__ = "etapas_orden"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    etapa_producto_id = Column(Integer, ForeignKey("etapas_producto.id"), nullable=True)
    etapa_produccion_id = Column(Integer, ForeignKey("etapas_produccion.id"), nullable=True)  # legacy
    area_id = Column(Integer, ForeignKey("areas_produccion.id"), nullable=True)
    estado = Column(String(20), nullable=False, default="pendiente")  # pendiente | en_curso | completada
    iteracion = Column(Integer, nullable=False, default=1)  # 1, 2, 3... para estuchados parciales
    nombre_display = Column(String(200), nullable=True)     # ej: "Estuchado 1", "Estuchado 2"
    fecha_inicio = Column(DateTime, nullable=True)
    fecha_fin = Column(DateTime, nullable=True)
    cantidad_obtenida = Column(Float, nullable=True)
    unidad_obtenida = Column(String(10), nullable=True)
    usuario_inicio_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    usuario_fin_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    orden = relationship("Orden", back_populates="etapas_orden")
    etapa_producto = relationship("EtapaProducto")
    area = relationship("AreaProduccion")
    usuario_inicio = relationship("Usuario", foreign_keys=[usuario_inicio_id])
    usuario_fin = relationship("Usuario", foreign_keys=[usuario_fin_id])


class EtapaMaestro(Base):
    __tablename__ = "etapas_maestro"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), unique=True, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    areas = relationship("AreaProduccion", back_populates="etapa", cascade="all, delete-orphan")


class AreaProduccion(Base):
    __tablename__ = "areas_produccion"

    id = Column(Integer, primary_key=True, index=True)
    etapa_id = Column(Integer, ForeignKey("etapas_maestro.id"), nullable=False)
    nombre = Column(String(150), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    etapa = relationship("EtapaMaestro", back_populates="areas")
    equipos = relationship("EquipoProduccion", back_populates="area", cascade="all, delete-orphan")


class EquipoProduccion(Base):
    __tablename__ = "equipos_produccion"

    id = Column(Integer, primary_key=True, index=True)
    area_id = Column(Integer, ForeignKey("areas_produccion.id"), nullable=False)
    nombre = Column(String(150), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    area = relationship("AreaProduccion", back_populates="equipos")


class AlertaConfig(Base):
    __tablename__ = "alertas_config"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False)
    dias_limite = Column(Integer, nullable=False)
    estado_aplica = Column(String(50), nullable=True)
    activo = Column(Boolean, default=True, nullable=False)


class ConfigSistema(Base):
    __tablename__ = "config_sistema"

    clave = Column(String(100), primary_key=True)
    valor = Column(Text, nullable=True)
