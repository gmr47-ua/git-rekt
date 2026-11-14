import streamlit as st
from PIL import Image
import numpy as np

#Configuracion inicial de la pagina (BASE DE DATOS LOCAL)
casos_data = {
    "Inundación de Valencia": {
        "descripcion": "Análisis de la cuenca baja tras las precipitaciones de otoño.",
        "antes": None, #aqui se pondran las rutas reales de las imagenes
        "despues": None,
        "area_inundada": "45.2 km²",
        "delta_area": "+12.4% vs ayer",
        "poblacion_afectada": "aprox. 12,500 hab",
        "delta_poblacion": "Estimacion preliminar",
        "fiabilidad_sar": "95%",
        "delta_fiabilidad": "Alta claridad en banda C",
        "informe_ia": "Los datos de retrodispersión de radar indican una expansión significativa de cuerpos de agua en la cuenca baja. La señal dieléctrica confirma saturación hídrica en zonas de cultivo adyacentes al cauce principal. Las nubes presentes en la zona impedían la visibilidad óptica tradicional, validando la necesidad crítica de datos SAR."
    },
    "Desborde de río Bangladesh": {
        #lo mismo que valencia pero otros datos
        "antes": None,
        "despues": None,
        "area_inundada": "120.5 km²",
        "delta_area": "+25.0% vs ayer",
        "poblacion_afectada": "aprox. 50,000 hab",
        "delta_poblacion": "Zona rural densamente poblada,",
        "fiabilidad_sar": "90%",
        "delta_fiabilidad": "Atravesando capa de nubes densas",
        "informe_ia": "El radar penetra la cobertura nubosa continua del monzón. Se observa un desbordamiento significativo del cauce principal, con expansión de agua hacia áreas agrícolas y residenciales. La señal SAR muestra alta saturación en zonas bajas, confirmando la extensión de la inundación."
    },
    "Zona agrícola en California": {
        "antes": None,
        "despues": None,
        "area_inundada": "30.0 km²",
        "delta_area": "+5.0% vs ayer",
        "poblacion_afectada": "aprox. 5,000 hab",
        "delta_poblacion": "Principalmente granjas y ranchos",
        "fiabilidad_sar": "92%",
        "delta_fiabilidad": "Condiciones óptimas de radar",
        "informe_ia": "El análisis SAR revela un aumento moderado en la superficie de agua en áreas agrícolas. La señal indica saturación en zonas de cultivo, pero sin impacto significativo en la infraestructura. La detección es confiable debido a la baja interferencia atmosférica y la claridad de la señal en banda C."
    }
}
# BARRA LATERAL DE CONTROLES
st.sidebar.title("PANEL DE CONTROL")
caso = st.sidebar.selectbox(
    "Selecciona un caso de estudio", 
list(casos_data.keys())
)

datos_actuales = casos_data[caso]

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
st.subheader(f"Análisis de radar para: {caso}")
st.write(datos_actuales.get("descripcion", "No hay descripción disponible para este caso."))
if modo_vista == "Comparación directa (antes/después)":
    st.info("Modo de visualización: Comparación directa (antes/después)")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Imagen de radar antes del evento")
        st.caption("Imagen de radar antes del evento")
        if datos_actuales.get("antes"):
            st.image(datos_actuales["antes"], use_container_width=True)
        else:
            st.info(f"[ IMAGEN DE RADAR - ANTES - {caso} ]")

    with col2:
        st.subheader("Imagen de radar después del evento")
        st.caption("Imagen de radar después del evento")
        if datos_actuales.get("despues"):
            st.image(datos_actuales["despues"], use_container_width=True)
        else:
            st.info(f"[ IMAGEN DE RADAR - DESPUÉS - {caso} ]")
    #st.image(data/despues_evento.png, use_container_width=True)
else:
    st.info("Modo de visualización: Superposición de radar (Capa de agua)")
    st.warning(f"Nivel de sensibilidad de opacidad aplicado: **{int(slider_valor * 100)}%**")
    if datos_actuales.get("despues"):
        st.image(datos_actuales["despues"], use_column_width=True)
    else:
        st.info(f"[ Vista unificada de radar con superposición de agua - {caso} ]")
        st.markdown("*Aqui tus compañerps podran integrar mas adelante un mapa interactivo o una imagen con la mascara de agua combinada.*")

st.markdown("---")

#3 METRICAS CLAVE U PANEL DE IA
col_metric1, col_metric2, col_metric3 = st.columns(3)

with col_metric1:
    st.metric(
        label="Área Inundada",
        value=datos_actuales.get("area_inundada", "N/A"),
        delta=datos_actuales.get("delta_area", "")
    )

with col_metric2:
    st.metric(
        label="Población Afectada",
        value=datos_actuales.get("poblacion_afectada", "N/A"),
        delta=datos_actuales.get("delta_poblacion", "")
    )

with col_metric3:
    st.metric(
        label="Fiabilidad de Detección SAR",
        value=datos_actuales.get("fiabilidad_deteccion", "N/A"),
        delta=datos_actuales.get("delta_fiabilidad", "")
    )

st.markdown("### INFORME DE ANÁLISIS Generado por IA")
with st.container():
    st.markdown(f"> {datos_actuales.get('informe_ia', 'No hay informe disponible para este caso.')}")

#BOTON INTERACTIVO PARA SIMULAR LLAMADA DE IA O ACTUALIZAR REPORTE
if st.button("Actualizar Informe de IA"):
    st.success("Informe actualizado con éxito.")