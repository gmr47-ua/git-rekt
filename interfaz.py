import streamlit as st
from PIL import Image
import numpy as np

#Configuracion inicial de la pagina
st.set_page_config(
    page_title="git rekt",
    page_icon=":robot_face:",
    layout="wide",
)

st.title("git rekt")
st.markdown("transformando observaciones complejas de radar en información visual")

# BARRA LATERAL DE CONTROLES
st.sidebar.title("CPANEL DE CONTROL")
caso = st.sidebar.selectbox(
    "Selecciona un caso de estudio", 
    ["Inundación de Valencia", "Desborde de río Bangladesh", "Zona agrícola en California"]
)

st.sidebar.markdown("---")
st.sidebar.subheader("Opciones de visualización")

modo_vista = st.sidebar.radio(
    "Selecciona el modo de visualización",
    ["Comparación directa (antes/después)", "Superposición de radar (Capa de agua)"]
)

slider_valor = st.sidebar.slider(
    "Nivel de opacidadd",
    0.0, 1.0, 0.5
)
st.sidebar.info("**TIP DE RADAR:** El SAR detecta el agua porque actúa como un espejo, reflejando la señal lejos del satélite, y mostrándose como zonas oscuras.")

#PANEL PRINCIPAL DE VISUALIZACIÓN
#Dos columnas para representar un antes y un después

col1, col2 = st.columns(2)

with col1:
    st.subheader("Imagen de radar antes del evento")
    st.caption("Imagen de radar antes del evento")
    # Cargar la imagen de radar antes del evento
    # usaremos una imagen de placeholder o color si no hay imagen disponible
    st.info("[ IMAGEN DE RADAR - ANTES ]")
    #st.image(data/antes_evento.png, use_container_width=True)

with col2:
    st.subheader("Imagen de radar después del evento")
    st.caption("Imagen de radar después del evento")
    # Cargar la imagen de radar después del evento
    # usaremos una imagen de placeholder o color si no hay imagen disponible
    st.info("[ IMAGEN DE RADAR - DESPUÉS ]")
    #st.image(data/despues_evento.png, use_container_width=True)

st.markdown("---")

#3 METRICAS CLAVE U PANEL DE IA
col_metric1, col_metric2, col_metric3 = st.columns(3)

with col_metric1:
    st.metric(label="Área Inundada Estimada", value="45.2 km²", delta="+12.4% vs ayer")

with col_metric2:
    st.metric(label="Población afectada Directamente", value=" aprox. 12,500 hab", delta="Estimacion preliminar")

with col_metric3:
    st.metric(label="Fiabilidad de Detección SAR", value="95%", delta="Alta claridad en banda C")

st.markdown("### INFORME DE ANÁLISIS Generado por IA")
with st.container():
    st.markdown("""
    > **Resumen Ejecutivo (Qwen):**
    > *Los datos de retrodispersión de radar indican una expansión significativa de cuerpos
    de agua en la cuenca baja. La señal dieléctrica confirma saturación hídrica en zonas de cultivo
    adyacentes al cauce principal. Las nubes. Las nubes presentes en la zona impedían la visibilidad óptica tradicional, validando
    la necesidad crítica de datos SAR.*
    """)

#BOTON INTERACTIVO PARA SIMULAR LLAMADA DE IA O ACTUALIZAR REPORTE
if st.button("Actualizar Informe de IA"):
    st.success("Informe actualizado con éxito.")