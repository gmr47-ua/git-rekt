import os
import sys
import json
from pathlib import Path
from typing import Union, Generator, Optional
from openai import OpenAI
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

BASE_URL = os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.ai/v1")
MODEL_ID = os.getenv("MODELSCOPE_MODEL", "Qwen-Ambassador/Qwen3.8-Omni-Flash")

SYSTEM_PROMPT_ES = """Eres FloodyLens AI, un asistente experto en hidrología, teledetección (radar SAR, Sentinel-1, NISAR) y gestión de emergencias por inundaciones.
Tu objetivo es analizar los datos estructurados en formato JSON recibidos desde la aplicación de detección y sensores para generar un informe de situación claro, profesional y estructurado en Markdown.

El informe debe redactarse íntegramente en español (incluidos todos los títulos de sección y niveles de alerta) y estructurarse con los siguientes puntos:
1. 🚨 **Nivel de Alerta y Resumen Ejecutivo**: Nivel de riesgo (Verde / Amarillo / Naranja / Rojo) y resumen del estado de emergencia.
2. 📊 **Evaluación de Datos Clave**: Interpretación del área anegada, datos de radar SAR, porcentaje de la escena y características morfológicas.
3. 📍 **Zonas Afectadas e Impacto**: Localización geográfica, impacto estimado en población e infraestructuras críticas en riesgo.
4. 🛠️ **Recomendaciones y Plan de Acción Inmediato**: Medidas de mitigación, zonas prioritarias y avisos a autoridades o población.

Usa un tono técnico pero accesible para la toma de decisiones rápidas."""

SYSTEM_PROMPT_EN = """You are FloodyLens AI, an expert assistant in hydrology, satellite remote sensing (SAR radar, Sentinel-1, NISAR), and flood emergency management.
Your goal is to analyze structured JSON data received from the detection application and sensors to generate a clear, professional, and well-structured situation report in Markdown.

The report MUST be written entirely in English (including all section titles and risk levels) and follow this exact structure:
1. 🚨 **Alert Level and Executive Summary**: Risk level (Green / Yellow / Orange / Red) and summary of the emergency situation.
2. 📊 **Key Data Assessment**: Interpretation of flooded area, SAR radar metrics, percentage of the scene, and morphological characteristics.
3. 📍 **Affected Areas and Impact**: Geographic location, estimated population impact, and critical infrastructure at risk.
4. 🛠️ **Recommendations and Immediate Action Plan**: Mitigation measures, priority response areas, and actionable advisories for authorities or the public.

Use a technical yet accessible and actionable tone for rapid decision-making."""

# Compatibilidad hacia atrás
SYSTEM_PROMPT = SYSTEM_PROMPT_ES


def get_client() -> OpenAI:
    """Obtiene el cliente OpenAI configurado para la API de ModelScope."""
    api_key = os.getenv("MODELSCOPE_API_KEY")
    if not api_key:
        raise ValueError(
            "Falta la variable de entorno MODELSCOPE_API_KEY. "
            "Asegúrate de configurarla en tu archivo .env o en el entorno."
        )
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def _convertir_a_json_string(datos: Union[dict, list, str, Path]) -> str:
    """
    Convierte la entrada (diccionario, archivo o string JSON) en una cadena JSON formateada.
    """
    # Si es una ruta a un archivo existente
    if isinstance(datos, (str, Path)) and os.path.isfile(str(datos)):
        with open(datos, "r", encoding="utf-8") as f:
            return f.read()

    # Si ya es un dict o list de Python
    if isinstance(datos, (dict, list)):
        return json.dumps(datos, indent=2, ensure_ascii=False)

    # Si es un string, verificar si es JSON válido
    if isinstance(datos, str):
        try:
            parsed = json.loads(datos)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            # Si no es JSON puro, se envía como texto
            return datos

    raise TypeError(f"Formato de datos no soportado: {type(datos)}")


def generar_informe(
    datos_json: Union[dict, list, str, Path],
    stream: bool = False,
    instrucciones_extra: Optional[str] = None,
    idioma: Optional[str] = None,
) -> Union[str, Generator[str, None, None]]:
    """
    Recibe los datos en formato JSON de la aplicación y solicita a Qwen
    la generación de un informe técnico en Markdown para mostrar en la interfaz.

    :param datos_json: Diccionario, string JSON o ruta al archivo .json
    :param stream: Si es True, devuelve un generador que emite fragmentos de texto (ideal para UIs en tiempo real).
                   Si es False, devuelve el informe completo como string.
    :param instrucciones_extra: Instrucciones opcionales añadidas al prompt (ej. "enfócate en evacuación").
    :param idioma: Idioma del informe ('es' o 'en'). Si no se especifica, se detecta de instrucciones_extra o por defecto 'es'.
    :return: String con el informe completo o Generador de chunks de texto si stream=True.
    """
    json_str = _convertir_a_json_string(datos_json)
    client = get_client()

    # Detectar si el idioma solicitado es inglés
    es_ingles = False
    if idioma:
        es_ingles = str(idioma).strip().lower().startswith("en")
    elif instrucciones_extra:
        inst_lower = instrucciones_extra.lower()
        es_ingles = any(k in inst_lower for k in ("english", "inglés", "ingles", "in english"))

    if es_ingles:
        system_prompt = SYSTEM_PROMPT_EN
        prompt_usuario = (
            f"Analyze the following flood JSON data and generate the technical report in English:\n\n"
            f"```json\n{json_str}\n```"
        )
        if instrucciones_extra:
            prompt_usuario += f"\n\nAdditional instructions: {instrucciones_extra}"
    else:
        system_prompt = SYSTEM_PROMPT_ES
        prompt_usuario = (
            f"Analiza los siguientes datos JSON de inundación y genera el informe técnico:\n\n"
            f"```json\n{json_str}\n```"
        )
        if instrucciones_extra:
            prompt_usuario += f"\n\nInstrucciones adicionales: {instrucciones_extra}"

    # Nota: Los modelos Omni en ModelScope funcionan con stream=True
    completion = client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_usuario},
        ],
        stream=True,
    )

    def _stream_generator() -> Generator[str, None, None]:
        for chunk in completion:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    if stream:
        return _stream_generator()
    else:
        # Acumular todos los tokens y devolver el informe completo
        partes = []
        for fragmento in _stream_generator():
            partes.append(fragmento)
        return "".join(partes)


def informe_local(nombre: str, stats: dict, idioma: str = "es") -> str:
    """Texto de respaldo sin IA (por si falla la red o la API)."""
    if str(idioma).strip().lower().startswith("en"):
        area = stats.get("Area inundada", stats.get("Flooded area", "N/A"))
        sensor = stats.get("Sensor", "N/A")
        return (
            f"In **{nombre}** the SAR analysis ({sensor}) detects a flooded area of {area}. "
            "Calm water reflects the radar signal away from the satellite and looks dark, "
            "which makes it possible to map it even through clouds or at night. "
            "NISAR (L-band) data will extend this monitoring to a global scale."
        )
    area = stats.get("Area inundada", "N/D")
    sensor = stats.get("Sensor", "N/D")
    return (
        f"En **{nombre}** el análisis SAR ({sensor}) detecta un área inundada de {area}. "
        "El agua en calma refleja la señal del radar lejos del satélite y aparece oscura, "
        "lo que permite delimitarla incluso con nubes o de noche. "
        "Los datos de NISAR (banda L) permitirán ampliar este seguimiento a nivel global."
    )


# Alias amigable para los compañeros
analizar_json = generar_informe


if __name__ == "__main__":
    # Permite ejecutar el script por línea de comandos:
    # 1. python qwen.py ruta/a/datos.json
    # 2. python qwen.py (usará el archivo de ejemplo o muestra de prueba)
    if len(sys.argv) > 1:
        parametro = sys.argv[1]
        print(f"Generando informe a partir de: {parametro}\n" + "=" * 60)
        try:
            for chunk in generar_informe(parametro, stream=True):
                print(chunk, end="", flush=True)
            print()
        except Exception as e:
            print(f"Error generando informe: {e}")
    else:
        # Comprobar si existe ejemplo_datos.json
        ruta_ejemplo = Path(__file__).parent / "ejemplo_datos.json"
        if ruta_ejemplo.exists():
            print(f"Ejecutando con datos de prueba desde '{ruta_ejemplo.name}'...\n" + "=" * 60)
            for chunk in generar_informe(ruta_ejemplo, stream=True):
                print(chunk, end="", flush=True)
            print()
        else:
            datos_demo = {
                "municipio": "Zona de prueba",
                "alerta": "NARANJA",
                "nivel_agua_m": 3.1,
                "umbral_desbordamiento_m": 2.8,
            }
            print("Ejecutando con datos demo en memoria...\n" + "=" * 60)
            for chunk in generar_informe(datos_demo, stream=True):
                print(chunk, end="", flush=True)
            print()
