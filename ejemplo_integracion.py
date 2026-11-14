"""
Ejemplo de integración para el equipo de FloodLens:
- Compañero 1 (Aplicación/Detección): Cómo generar o pasar el JSON.
- Morci (IA - qwen.py): Procesa el JSON y genera el informe técnico.
- Compañero 2 (Interfaz de Usuario): Cómo recibir el informe y mostrarlo.
"""

from pathlib import Path
from qwen import generar_informe


# =====================================================================
# 1. PARTE DE LA APLICACIÓN (Compañero 1)
# La aplicación recopila o calcula datos y los deja en un diccionario
# =====================================================================
datos_de_la_aplicacion = {
    "timestamp": "2026-11-14T12:00:00Z",
    "municipio": "Paiporta",
    "precipitacion_acumulada_24h_mm": 285.4,
    "nivel_agua_m": 4.85,
    "umbral_desbordamiento_m": 3.20,
    "estado_sensor": "Desbordamiento activo",
    "estimacion_riesgo": {
        "nivel_alerta": "ROJO",
        "poblacion_afectada_estimada": 25000,
    },
}


# =====================================================================
# 2. PARTE DE LA INTERFAZ (Compañero 2)
# Opción A: Obtener el informe completo en texto para mostrarlo en la UI
# =====================================================================
def ejemplo_para_interfaz_texto_completo():
    print("--- [INTERFAZ] Solicitando informe completo a la IA ---")
    informe_markdown = generar_informe(datos_de_la_aplicacion, stream=False)

    # Aquí el compañero de la interfaz mostraría el markdown en pantalla
    # (por ejemplo en Streamlit: st.markdown(informe_markdown), o en Tkinter/Gradio)
    print(informe_markdown)


# =====================================================================
# Opción B: Mostrar el informe con efecto mecanografía (streaming)
# =====================================================================
def ejemplo_para_interfaz_en_tiempo_real():
    print("\n--- [INTERFAZ] Mostrando informe en tiempo real (streaming) ---")
    # En Streamlit se puede hacer directamente con st.write_stream(...)
    for chunk in generar_informe(datos_de_la_aplicacion, stream=True):
        print(chunk, end="", flush=True)
    print()


if __name__ == "__main__":
    # Prueba la opción A
    ejemplo_para_interfaz_texto_completo()
