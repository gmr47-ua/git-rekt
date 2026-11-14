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

SYSTEM_PROMPT = """Eres FloodLens AI, un asistente experto en hidrología, teledetección y gestión de emergencias por inundaciones.
Tu objetivo es analizar los datos estructurados en formato JSON recibidos desde la aplicación de detección y sensores para generar un informe de situación claro, profesional y estructurado en Markdown.

El informe debe estructurarse con los siguientes puntos:
1. 🚨 **Nivel de Alerta y Resumen Ejecutivo**: Nivel de riesgo (Verde / Amarillo / Naranja / Rojo) y resumen del estado de emergencia.
2. 📊 **Evaluación de Datos Clave**: Interpretación de lluvia acumulada, niveles de caudal vs. umbrales y áreas anegadas.
3. 📍 **Zonas Afectadas e Impacto**: Infraestructuras críticas comprometidas y población en riesgo.
4. 🛠️ **Recomendaciones y Plan de Acción Inmediato**: Medidas de mitigación, zonas a evacuar y avisos a la población o autoridades.

Usa un tono técnico pero accesible para la toma de decisiones rápidas."""


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
) -> Union[str, Generator[str, None, None]]:
    """
    Recibe los datos en formato JSON de la aplicación y solicita a Qwen
    la generación de un informe técnico en Markdown para mostrar en la interfaz.

    :param datos_json: Diccionario, string JSON o ruta al archivo .json
    :param stream: Si es True, devuelve un generador que emite fragmentos de texto (ideal para UIs en tiempo real).
                   Si es False, devuelve el informe completo como string.
    :param instrucciones_extra: Instrucciones opcionales añadidas al prompt (ej. "enfócate en evacuación").
    :return: String con el informe completo o Generador de chunks de texto si stream=True.
    """
    json_str = _convertir_a_json_string(datos_json)
    client = get_client()

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
            {"role": "system", "content": SYSTEM_PROMPT},
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


def informe_local(nombre: str, stats: dict) -> str:
    """Texto de respaldo sin IA (por si falla la red o la API)."""
    area = stats.get("Area inundada", "N/D")
    sensor = stats.get("Sensor", "N/D")
    return (
        f"En **{nombre}** el analisis SAR ({sensor}) detecta un area inundada de {area}. "
        "El agua en calma refleja la senal del radar lejos del satelite y aparece oscura, "
        "lo que permite delimitarla incluso con nubes o de noche. "
        "Los datos de NISAR (banda L) permitiran ampliar este seguimiento a nivel global."
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
