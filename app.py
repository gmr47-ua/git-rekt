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
from dotenv import load_dotenv

from qwen import generar_informe, informe_local

load_dotenv()  # Carga variables de entorno desde .env
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


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
COLOR_SENSOR = {"sentinel": "#1f6feb", "nisar": "#d9480f"}  # azul = Sentinel, naranja = NISAR
COLOR_AGUA = {"sentinel": (0, 110, 255), "nisar": (255, 140, 0)}  # relleno de la mancha de agua


def fecha_legible(iso):
    """'2024-10-19' -> '19 oct 2024'. Si no se puede interpretar, devuelve el texto tal cual."""
    try:
        a, m, d = str(iso).split("-")
        return f"{int(d)} {MESES[int(m) - 1]} {a}"
    except (ValueError, IndexError):
        return str(iso) if iso else "fecha N/D"


def chip_sensor(texto, clave):
    """Etiqueta de color para que se distinga siempre de que satelite viene cada imagen."""
    st.markdown(
        f"<span style='background:{COLOR_SENSOR[clave]};color:#fff;padding:4px 12px;"
        f"border-radius:999px;font-weight:600;font-size:0.9rem;'>{texto}</span>",
        unsafe_allow_html=True,
    )


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
def preparar_overlay(ruta: str, mtime: float, color=(0, 110, 255)):
    """Mascara -> PNG RGBA del color indicado, reproyectado a EPSG:4326 + limites [[S,O],[N,E]].
    Sirve para cualquier CRS (la de Sentinel esta en lat/lon y la de NISAR en UTM)."""
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
    rgba[destino == 1] = [*color, 255]
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii"), [[sur, oeste], [norte, este]]


@st.cache_data(show_spinner=False)
def par_imagenes_b64(ruta_a: str, ruta_d: str, mtime_a: float, mtime_d: float, max_lado=1400):
    """Carga antes/despues, las iguala de tamano y las devuelve en base64 (JPEG ligero)."""
    a = Image.open(ruta_a).convert("RGB")
    d = Image.open(ruta_d).convert("RGB")
    if d.size != a.size:
        d = d.resize(a.size, Image.BILINEAR)
    a.thumbnail((max_lado, max_lado))
    d.thumbnail((max_lado, max_lado))
    salida = []
    for img in (a, d):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        salida.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    return salida[0], salida[1]


SLIDER_HTML = """
<div id="cmp" style="position:relative;width:100%;height:__ALTO__px;overflow:hidden;
     border-radius:8px;background:#111;user-select:none;touch-action:none;cursor:ew-resize;">
  <img src="data:image/jpeg;base64,__DESPUES__"
       style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;" draggable="false">
  <div id="top" style="position:absolute;inset:0;clip-path:inset(0 50% 0 0);">
    <img src="data:image/jpeg;base64,__ANTES__"
         style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;" draggable="false">
  </div>
  <div id="bar" style="position:absolute;top:0;bottom:0;left:50%;width:3px;background:#fff;
       transform:translateX(-50%);box-shadow:0 0 6px rgba(0,0,0,.6);">
    <div style="position:absolute;top:50%;left:50%;width:38px;height:38px;border-radius:50%;
         background:#fff;transform:translate(-50%,-50%);display:flex;align-items:center;
         justify-content:center;font:bold 16px sans-serif;color:#222;box-shadow:0 0 8px rgba(0,0,0,.6);">&#8596;</div>
  </div>
  <span style="position:absolute;top:10px;left:10px;background:rgba(0,0,0,.65);color:#fff;
        padding:4px 10px;border-radius:4px;font:600 13px sans-serif;">__ETQ_A__</span>
  <span style="position:absolute;top:10px;right:10px;background:rgba(0,0,0,.65);color:#fff;
        padding:4px 10px;border-radius:4px;font:600 13px sans-serif;">__ETQ_D__</span>
  <span style="position:absolute;bottom:10px;left:50%;transform:translateX(-50%);background:__COLOR__;
        color:#fff;padding:4px 14px;border-radius:999px;font:700 13px sans-serif;">__SENSOR__</span>
</div>
<script>
  const c = document.getElementById("cmp"), top_ = document.getElementById("top"),
        bar = document.getElementById("bar");
  let drag = false;
  function mover(e) {
    const r = c.getBoundingClientRect();
    let p = (e.clientX - r.left) / r.width;
    p = Math.max(0, Math.min(1, p));
    top_.style.clipPath = "inset(0 " + ((1 - p) * 100) + "% 0 0)";
    bar.style.left = (p * 100) + "%";
  }
  c.addEventListener("pointerdown", e => { drag = true; c.setPointerCapture(e.pointerId); mover(e); });
  c.addEventListener("pointermove", e => { if (drag) mover(e); });
  c.addEventListener("pointerup", () => { drag = false; });
</script>
"""


def mostrar_slider(ruta_a: Path, ruta_d: Path, alto=520, sensor="", clave="sentinel",
                   fecha_a=None, fecha_d=None):
    a64, d64 = par_imagenes_b64(
        str(ruta_a), str(ruta_d), ruta_a.stat().st_mtime, ruta_d.stat().st_mtime
    )
    html = (
        SLIDER_HTML.replace("__ALTO__", str(alto))
        .replace("__ANTES__", a64)
        .replace("__DESPUES__", d64)
        .replace("__ETQ_A__", f"ANTES &middot; {fecha_legible(fecha_a)}")
        .replace("__ETQ_D__", f"DESPU&Eacute;S &middot; {fecha_legible(fecha_d)}")
        .replace("__SENSOR__", sensor or "")
        .replace("__COLOR__", COLOR_SENSOR[clave])
    )
    if hasattr(st, "iframe"):          # Streamlit reciente
        st.iframe(html, height=alto + 10)
    else:                              # versiones antiguas
        import streamlit.components.v1 as components
        components.html(html, height=alto + 10)


@st.cache_data(show_spinner=False)
def imagen_con_agua_png(ruta_d: str, ruta_m: str, opacidad: float, mtime_d: float, mtime_m: float):
    """Imagen 'despues' con la mascara de agua en azul encima -> bytes PNG."""
    base = Image.open(ruta_d).convert("RGBA")
    with rasterio.open(ruta_m) as src:
        agua = src.read(1) == 1
    mascara = Image.fromarray((agua * 255).astype(np.uint8)).resize(base.size, Image.NEAREST)
    hay_agua = np.array(mascara) > 0
    capa = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
    capa[hay_agua] = [0, 110, 255, int(255 * opacidad)]
    final = Image.alpha_composite(base, Image.fromarray(capa, mode="RGBA"))
    buf = io.BytesIO()
    final.save(buf, format="PNG")
    return buf.getvalue()


def construir_mapa(png_b64, limites, centro, opacidad, zonas=None, agua_nisar=None):
    """zonas: lista de (nombre, poligono [[lat, lon], ...], color) con la cobertura de cada sensor."""
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
        name="🟦 Agua nueva Sentinel-1 (banda C)",
        interactive=False,
        zindex=2,
    ).add_to(m)
    if agua_nisar:  # (png_b64, limites) de la mascara de NISAR, en otro color
        folium.raster_layers.ImageOverlay(
            image="data:image/png;base64," + agua_nisar[0],
            bounds=agua_nisar[1],
            opacity=opacidad,
            name="🟧 Agua nueva NISAR (banda L)",
            interactive=False,
            zindex=3,
        ).add_to(m)
    todos = [limites[0], limites[1]]
    for nombre_z, poligono, color in (zonas or []):
        folium.Polygon(
            locations=poligono,
            color=color, weight=3, fill=True, fill_color=color, fill_opacity=0.07,
            tooltip=nombre_z, name=nombre_z,
            interactive=True,   # solo el borde/relleno ligero; no tapa el mapa
        ).add_to(m)
        todos.extend(poligono)
    # Encuadre: que quepan TODAS las zonas (NISAR es la mayor), no solo la mascara
    lats = [p[0] for p in todos]
    lons = [p[1] for p in todos]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
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
    [
        "Comparación directa (antes/después)",
        "Comparación NISAR (banda L)",
        "Superposición de radar (Capa de agua)",
    ],
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

nisar = {}
ruta_nisar = carpeta / "nisar.json" if carpeta else None
if ruta_nisar and ruta_nisar.exists():
    try:
        nisar = cargar_json(str(ruta_nisar), ruta_nisar.stat().st_mtime)
    except json.JSONDecodeError as e:
        st.error(f"`{ruta_nisar}` no es un JSON válido: {e}")

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
partes = []
if sensor != "N/D":
    partes.append(f"Sensor: {sensor}")
if datos.get("polarizacion"):
    partes.append(f"Polarización: {datos['polarizacion']}")
if datos.get("fecha_antes") and datos.get("fecha_despues"):
    partes.append(f"Imágenes: {datos['fecha_antes']} → {datos['fecha_despues']}")
if partes:
    st.caption(" · ".join(partes))
if nisar:
    st.caption(
        f"Datos adicionales: {nisar.get('sensor', 'NISAR')} · {nisar.get('polarizacion', 'N/D')} · "
        f"{fecha_legible(nisar.get('fecha_antes'))} → {fecha_legible(nisar.get('fecha_despues'))} "
        "(ver modo «Comparación NISAR»)"
    )
if "no_validada" in str(datos.get("estado", "")):
    st.info(
        "Resultado exploratorio: superficie candidata a agua nueva, "
        "sin validación independiente. Consulta las limitaciones más abajo."
    )
if carpeta is None:
    st.warning(
        "Aún no hay datos. Crea una carpeta `data/<caso>/` con `results.json` y "
        "`mascara_agua.tif` (los genera `procesamiento.py`)."
    )

if modo_vista.startswith("Comparación directa"):
    img_a = encontrar_imagen(carpeta, "antes")
    img_d = encontrar_imagen(carpeta, "despues")
    if img_a and img_d:
        etiqueta_s1 = f"🛰️ {sensor if sensor != 'N/D' else 'Sentinel-1 (banda C)'}"
        chip_sensor(etiqueta_s1 + f" · {datos.get('polarizacion', 'N/D')}", "sentinel")
        st.caption("Arrastra el control deslizante para comparar el radar antes y después del evento.")
        try:
            mostrar_slider(
                Path(img_a), Path(img_d),
                sensor=etiqueta_s1, clave="sentinel",
                fecha_a=datos.get("fecha_antes"), fecha_d=datos.get("fecha_despues"),
            )
        except Exception as e:
            st.error(f"No se pudieron cargar las imágenes: {e}")
    else:
        col1, col2 = st.columns(2)
        col1.info(f"[ IMAGEN DE RADAR - ANTES - {caso} ]")
        col2.info(f"[ IMAGEN DE RADAR - DESPUÉS - {caso} ]")
elif modo_vista.startswith("Comparación NISAR"):
    n_a = encontrar_imagen(carpeta, "nisar_antes")
    n_d = encontrar_imagen(carpeta, "nisar_despues")
    if n_a and n_d:
        etiqueta_n = f"📡 {nisar.get('sensor', 'NISAR (banda L)')}"
        chip_sensor(etiqueta_n + f" · {nisar.get('polarizacion', 'N/D')}", "nisar")
        st.caption(
            "Arrastra el control deslizante para comparar NISAR entre "
            f"{fecha_legible(nisar.get('fecha_antes'))} y {fecha_legible(nisar.get('fecha_despues'))}."
        )
        try:
            mostrar_slider(
                Path(n_a), Path(n_d),
                sensor=etiqueta_n, clave="nisar",
                fecha_a=nisar.get("fecha_antes"), fecha_d=nisar.get("fecha_despues"),
            )
        except Exception as e:
            st.error(f"No se pudieron cargar las imágenes de NISAR: {e}")
        st.warning(
            "**No es el mismo evento que el análisis de Sentinel-1.** Las fechas son distintas y los "
            "sensores también (banda L frente a banda C), así que los valores en dB no son "
            "directamente comparables. Las métricas de más abajo (área, informe de IA) "
            "proceden únicamente de Sentinel-1."
        )
    else:
        st.info(
            "Faltan `nisar_antes.png` / `nisar_despues.png` en la carpeta del caso. "
            "Genéralos con `py exportar_nisar.py <antes.tif> <despues.tif> data/<caso>`."
        )
else:
    if hay_mascara:
        try:
            png_b64, limites = preparar_overlay(
                str(ruta_mascara), ruta_mascara.stat().st_mtime, COLOR_AGUA["sentinel"]
            )
            ruta_mascara_n = carpeta / "nisar_mascara_agua.tif"
            agua_nisar = None
            if ruta_mascara_n.exists():
                agua_nisar = preparar_overlay(
                    str(ruta_mascara_n), ruta_mascara_n.stat().st_mtime, COLOR_AGUA["nisar"]
                )
            centro = parse_centroide(primero(datos, ["centroide", "centroid"])) or (
                (limites[0][0] + limites[1][0]) / 2,
                (limites[0][1] + limites[1][1]) / 2,
            )
            zonas = [(
                "🟦 Zona Sentinel-1 (banda C)",
                [[limites[0][0], limites[0][1]], [limites[1][0], limites[0][1]],
                 [limites[1][0], limites[1][1]], [limites[0][0], limites[1][1]]],
                COLOR_SENSOR["sentinel"],
            )]
            if nisar.get("poligono_wgs84"):
                zonas.append(("🟧 Zona NISAR (banda L)", nisar["poligono_wgs84"], COLOR_SENSOR["nisar"]))
            st_folium(
                construir_mapa(png_b64, limites, centro, opacidad, zonas, agua_nisar),
                width=None,
                height=600,
                returned_objects=[],
            )
            c1, c2 = st.columns(2)
            with c1:
                chip_sensor("Zona Sentinel-1 (banda C)", "sentinel")
            with c2:
                if nisar.get("poligono_wgs84"):
                    chip_sensor("Zona NISAR (banda L) · más extensa", "nisar")
                elif nisar:
                    st.caption("Vuelve a ejecutar `exportar_nisar.py` para dibujar también la zona de NISAR.")
            det = nisar.get("deteccion")
            if agua_nisar and det:
                st.caption(
                    f"Agua nueva en azul = Sentinel-1 ({fecha_legible(datos.get('fecha_antes'))} → "
                    f"{fecha_legible(datos.get('fecha_despues'))}). Agua nueva en naranja = NISAR "
                    f"({fecha_legible(nisar.get('fecha_antes'))} → {fecha_legible(nisar.get('fecha_despues'))}, "
                    f"≈ {det['hectareas_afectadas'] / 100:.1f} km² candidatos). "
                    "Son eventos y fechas distintos: no se pueden sumar ni comparar como un solo resultado."
                )
            elif nisar and not agua_nisar:
                st.caption("Falta `nisar_mascara_agua.tif`: vuelve a ejecutar `exportar_nisar.py` para dibujar el agua de NISAR.")
        except Exception as e:
            st.error(f"No se pudo leer `{ruta_mascara}`: {e}")
    else:
        st.info(f"[ Vista de radar con superposición de agua - {caso} ]")

resumen = encontrar_imagen(carpeta, "resumen")
if resumen:
    with st.expander("Análisis completo de la escena (antes, después, cambio y resultado)"):
        st.image(resumen, width="stretch")

st.markdown("---")

# ----------------------------------------------------------------------
# DESCARGAS
# ----------------------------------------------------------------------
slug = (carpeta.name if carpeta else "caso").lower()
img_despues = encontrar_imagen(carpeta, "despues")
d1, d2, d3 = st.columns(3)

if img_despues and hay_mascara:
    png_bytes = imagen_con_agua_png(
        img_despues, str(ruta_mascara), opacidad,
        Path(img_despues).stat().st_mtime, ruta_mascara.stat().st_mtime,
    )
    d1.download_button(
        "⬇️ Imagen con zona inundada (PNG)", png_bytes,
        file_name=f"{slug}_inundacion.png", mime="image/png", width="stretch",
    )
else:
    d1.button("⬇️ Imagen con zona inundada (PNG)", disabled=True, width="stretch")

if hay_mascara:
    d2.download_button(
        "⬇️ Máscara de agua (GeoTIFF)", ruta_mascara.read_bytes(),
        file_name=f"{slug}_mascara_agua.tif", mime="image/tiff", width="stretch",
    )
else:
    d2.button("⬇️ Máscara de agua (GeoTIFF)", disabled=True, width="stretch")

if datos:
    d3.download_button(
        "⬇️ Resultados (JSON)", json.dumps(datos, indent=2, ensure_ascii=False),
        file_name=f"{slug}_results.json", mime="application/json", width="stretch",
    )
else:
    d3.button("⬇️ Resultados (JSON)", disabled=True, width="stretch")

# ----------------------------------------------------------------------
# METRICAS
# ----------------------------------------------------------------------
pct_escena = primero(datos, ["porcentaje_candidato_original", "porcentaje_inundado"])
n_manchas = primero(datos, ["componentes_en_cuadricula_metrica", "num_manchas"])
perimetro = primero(datos, ["perimetro", "perimeter"])

m1, m2, m3 = st.columns(3)
m1.metric("Área Inundada", fmt(area_km2, 1, " km²"), datos.get("delta_area"))

# Si no hay poblacion / fiabilidad, se muestran metricas que si estan calculadas
if poblacion is not None:
    m2.metric("Población Afectada", fmt(poblacion, 0, " hab"), datos.get("delta_poblacion"))
else:
    m2.metric("Porcentaje de la escena", fmt(pct_escena, 1, "%"), "Píxeles candidatos / píxeles válidos")

if fiabilidad is not None:
    m3.metric("Fiabilidad de Detección SAR", fmt(fiabilidad, 0, "%"), datos.get("delta_fiabilidad"))
else:
    m3.metric("Manchas de agua detectadas", fmt(n_manchas, 0), "Componentes conectados")

with st.expander("Detalles morfológicos"):
    m4, m5, m6 = st.columns(3)
    if perimetro is not None and float(perimetro) >= 1000:
        m4.metric("Perímetro", fmt(float(perimetro) / 1000, 1, " km"))
    else:
        m4.metric("Perímetro", fmt(perimetro, 1, " m"))
    m5.metric("Compactación", fmt(primero(datos, ["compactacion", "compactness"]), 4))
    m6.metric("Elongación", fmt(primero(datos, ["elongacion", "elongation"]), 3))
    hu = primero(datos, ["momentos_hu", "hu_moments"])
    if hu:
        st.dataframe(
            {"Momento": [f"Hu{i + 1}" for i in range(len(hu))], "Valor": hu},
            hide_index=True,
        )

limitaciones = datos.get("limitaciones")
parametros = datos.get("parametros")
if limitaciones or parametros:
    with st.expander("Limitaciones y método"):
        if parametros:
            st.markdown(
                "**Parámetros de detección:** "
                + ", ".join(f"`{k}` = {v}" for k, v in parametros.items())
            )
        if limitaciones:
            st.markdown("**Limitaciones:**")
            for lim in limitaciones:
                st.markdown(f"- {lim}")

# ----------------------------------------------------------------------
# INFORME DE IA
# ----------------------------------------------------------------------
st.markdown("### INFORME DE ANÁLISIS Generado por IA")

stats_ia = {
    "Area inundada": fmt(area_km2, 1, " km2"),
    "Sensor": sensor,
    "Polarizacion": datos.get("polarizacion", "N/D"),
    "Fecha antes": datos.get("fecha_antes", "N/D"),
    "Fecha despues": datos.get("fecha_despues", "N/D"),
    "Porcentaje de la escena con agua nueva": fmt(pct_escena, 1, " %"),
    "Manchas de agua": fmt(n_manchas, 0),
    "Elongacion de la mancha": fmt(primero(datos, ["elongacion", "elongation"]), 3),
    "Poblacion afectada": fmt(poblacion, 0, " hab") if poblacion is not None else "N/D",
    "Estado del resultado": datos.get("estado", "N/D"),
    "Limitacion principal": (datos.get("limitaciones") or ["N/D"])[0],
}

clave_informe = f"informe::{caso}"
if st.button("Actualizar Informe de IA"):
    try:
        datos_para_ia = {
            "caso": nombre,
            "descripcion": descripcion,
            **datos,
            **stats_ia,
        }
        with st.container():
            texto = st.write_stream(generar_informe(datos_para_ia, stream=True))
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
    if "\n" in texto:
        st.markdown(texto)
    else:
        st.markdown(f"> {texto}")