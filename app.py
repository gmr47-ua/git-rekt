import base64
import io
import json
from pathlib import Path

import folium
import numpy as np
import rasterio
import streamlit as st
from PIL import Image
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from streamlit_folium import st_folium

from ia_informe import generar_informe_stream, informe_local

DATA_DIR = Path("data")

st.set_page_config(page_title="FloodyLens", page_icon="🌊", layout="wide")


# ----------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------
def primero(d: dict, claves, defecto=None):
    """Devuelve el valor de la primera clave que exista en d."""
    for k in claves:
        if k in d and d[k] is not None:
            return d[k]
    return defecto


def fmt(valor, decimales=2, sufijo=""):
    if valor is None:
        return "N/D"
    try:
        return f"{float(valor):,.{decimales}f}{sufijo}"
    except (TypeError, ValueError):
        return str(valor)


def parse_centroide(c):
    if isinstance(c, dict):
        lat = c.get("lat", c.get("y"))
        lon = c.get("lon", c.get("lng", c.get("x")))
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    elif isinstance(c, (list, tuple)) and len(c) == 2:
        return float(c[0]), float(c[1])
    return None


def listar_casos() -> dict:
    """{nombre_visible: carpeta} para cada subcarpeta de data/."""
    casos = {}
    if DATA_DIR.exists():
        for carpeta in sorted(p for p in DATA_DIR.iterdir() if p.is_dir()):
            casos[carpeta.name.replace("_", " ").title()] = carpeta
    return casos


def encontrar_imagen(carpeta, base: str):
    if carpeta is None:
        return None
    for ext in (".png", ".jpg", ".jpeg"):
        ruta = carpeta / f"{base}{ext}"
        if ruta.exists():
            return str(ruta)
    return None


@st.cache_data(show_spinner=False)
def cargar_json(ruta: str, mtime: float):
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner="Preparando capa de agua...")
def preparar_overlay(ruta: str, mtime: float):
    """Mascara -> PNG RGBA azul reproyectado a EPSG:4326 + limites [[S,O],[N,E]]."""
    with rasterio.open(ruta) as src:
        dst_crs = "EPSG:4326"
        transform, ancho, alto = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        destino = np.zeros((alto, ancho), dtype=np.uint8)
        reproject(
            source=rasterio.band(src, 1),
            destination=destino,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )
        oeste, sur, este, norte = array_bounds(alto, ancho, transform)

    rgba = np.zeros((alto, ancho, 4), dtype=np.uint8)
    rgba[destino > 0] = [0, 110, 255, 255]
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), [[sur, oeste], [norte, este]]


def construir_mapa(png_b64, limites, centro, opacidad):
    m = folium.Map(location=centro, tiles=None, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="Calles (OSM)").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, Maxar, Earthstar Geographics",
        name="Satelite (Esri)",
    ).add_to(m)
    folium.raster_layers.ImageOverlay(
        image="data:image/png;base64," + png_b64,
        bounds=limites,
        opacity=opacidad,
        name="Zona inundada (SAR)",
        interactive=False,
        zindex=2,
    ).add_to(m)
    m.fit_bounds(limites)
    folium.LayerControl(collapsed=False).add_to(m)
    return m


# ----------------------------------------------------------------------
# BARRA LATERAL
# ----------------------------------------------------------------------
casos = listar_casos()
if not casos:
    casos = {"Sin datos todavia": None}

st.sidebar.title("PANEL DE CONTROL")
caso = st.sidebar.selectbox("Selecciona un caso de estudio", list(casos.keys()))
carpeta = casos[caso]

st.sidebar.markdown("---")
st.sidebar.subheader("Opciones de visualización")
modo_vista = st.sidebar.radio(
    "Selecciona el modo de visualización",
    ["Comparación directa (antes/después)", "Superposición de radar (Capa de agua)"],
)
opacidad = st.sidebar.slider("Nivel de opacidad de la capa de agua", 0.0, 1.0, 0.65, 0.05)
st.sidebar.info(
    "**TIP DE RADAR:** El SAR detecta el agua porque actúa como un espejo, "
    "reflejando la señal lejos del satélite, y mostrándose como zonas oscuras."
)

# ----------------------------------------------------------------------
# CARGA DE DATOS DEL CASO
# ----------------------------------------------------------------------
datos = {}
ruta_json = carpeta / "results.json" if carpeta else None
if ruta_json and ruta_json.exists():
    try:
        datos = cargar_json(str(ruta_json), ruta_json.stat().st_mtime)
    except json.JSONDecodeError as e:
        st.error(f"`{ruta_json}` no es un JSON válido: {e}")

ruta_mascara = carpeta / "mascara_agua.tif" if carpeta else None
hay_mascara = bool(ruta_mascara and ruta_mascara.exists())

nombre = datos.get("nombre", caso)
descripcion = datos.get("descripcion", "")

# Cifras derivadas (todo sale del JSON; lo que falte aparece como N/D)
ha = primero(datos, ["hectareas_afectadas", "hectareas", "area_ha"])
area_km2 = float(ha) / 100 if ha is not None else primero(datos, ["area_km2"])
poblacion = primero(datos, ["poblacion_afectada"])
fiabilidad = primero(datos, ["fiabilidad", "fiabilidad_sar"])
sensor = primero(datos, ["sensor"], "N/D")

# ----------------------------------------------------------------------
# PANEL PRINCIPAL
# ----------------------------------------------------------------------
st.title("🌊 FloodyLens")
st.subheader(f"Análisis de radar para: {nombre}")
st.write(descripcion or "No hay descripción disponible para este caso.")
if sensor != "N/D":
    st.caption(f"Sensor: {sensor}")
if carpeta is None:
    st.warning(
        "Aún no hay datos. Crea una carpeta `data/<caso>/` con `results.json` y "
        "`mascara_agua.tif` (los genera `procesamiento.py`)."
    )

if modo_vista.startswith("Comparación"):
    col1, col2 = st.columns(2)
    for col, base, titulo in (
        (col1, "antes", "Imagen de radar antes del evento"),
        (col2, "despues", "Imagen de radar después del evento"),
    ):
        with col:
            st.subheader(titulo)
            img = encontrar_imagen(carpeta, base)
            if img:
                st.image(img, use_container_width=True)
            else:
                st.info(f"[ IMAGEN DE RADAR - {base.upper()} - {caso} ]")
else:
    if hay_mascara:
        try:
            png_b64, limites = preparar_overlay(str(ruta_mascara), ruta_mascara.stat().st_mtime)
            centro = parse_centroide(primero(datos, ["centroide", "centroid"])) or (
                (limites[0][0] + limites[1][0]) / 2,
                (limites[0][1] + limites[1][1]) / 2,
            )
            st_folium(
                construir_mapa(png_b64, limites, centro, opacidad),
                width=None,
                height=600,
                returned_objects=[],
            )
        except Exception as e:
            st.error(f"No se pudo leer `{ruta_mascara}`: {e}")
    else:
        st.info(f"[ Vista de radar con superposición de agua - {caso} ]")

st.markdown("---")

# ----------------------------------------------------------------------
# METRICAS
# ----------------------------------------------------------------------
m1, m2, m3 = st.columns(3)
m1.metric("Área Inundada", fmt(area_km2, 1, " km²"), datos.get("delta_area"))
m2.metric(
    "Población Afectada",
    fmt(poblacion, 0, " hab") if poblacion is not None else "N/D",
    datos.get("delta_poblacion"),
)
m3.metric(
    "Fiabilidad de Detección SAR",
    fmt(fiabilidad, 0, "%") if fiabilidad is not None else "N/D",
    datos.get("delta_fiabilidad"),
)

with st.expander("Detalles morfológicos"):
    m4, m5, m6 = st.columns(3)
    m4.metric("Perímetro", fmt(primero(datos, ["perimetro", "perimeter"]), 1))
    m5.metric("Compactación", fmt(primero(datos, ["compactacion", "compactness"]), 3))
    m6.metric("Elongación", fmt(primero(datos, ["elongacion", "elongation"]), 3))
    hu = primero(datos, ["momentos_hu", "hu_moments"])
    if hu:
        st.dataframe(
            {"Momento": [f"Hu{i + 1}" for i in range(len(hu))], "Valor": hu},
            hide_index=True,
        )

# ----------------------------------------------------------------------
# INFORME DE IA
# ----------------------------------------------------------------------
st.markdown("### INFORME DE ANÁLISIS Generado por IA")

stats_ia = {
    "Area inundada": fmt(area_km2, 1, " km2"),
    "Hectareas afectadas": fmt(ha, 1, " ha"),
    "Poblacion afectada": fmt(poblacion, 0, " hab") if poblacion is not None else "N/D",
    "Elongacion de la mancha": fmt(primero(datos, ["elongacion", "elongation"]), 3),
    "Compactacion": fmt(primero(datos, ["compactacion", "compactness"]), 3),
    "Sensor": sensor,
}

clave_informe = f"informe::{caso}"
if st.button("Actualizar Informe de IA"):
    try:
        with st.container():
            texto = st.write_stream(generar_informe_stream(nombre, descripcion, stats_ia))
        st.session_state[clave_informe] = texto
        st.success("Informe actualizado con éxito.")
    except Exception as e:
        st.warning(f"No se pudo contactar con la IA ({e}). Se muestra el informe local.")
        st.session_state[clave_informe] = informe_local(nombre, stats_ia)
        st.markdown(f"> {st.session_state[clave_informe]}")
else:
    texto = (
        st.session_state.get(clave_informe)
        or datos.get("informe_ia")
        or informe_local(nombre, stats_ia)
    )
    st.markdown(f"> {texto}")