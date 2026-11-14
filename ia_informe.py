import os

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.ai/v1")
MODEL_ID = os.getenv("MODELSCOPE_MODEL", "Qwen-Ambassador/Qwen3.8-Omni-Flash")

SYSTEM_PROMPT = (
    "Eres un analista de teledeteccion. Redactas informes breves (maximo 120 palabras) "
    "en espanol sobre inundaciones detectadas con radar de apertura sintetica (SAR). "
    "Usa EXCLUSIVAMENTE las cifras que se te dan; si un dato figura como N/D, "
    "di que no esta disponible. No inventes cifras, fechas ni sensores. "
    "Explica con claridad por que el radar es util (atraviesa nubes, de noche y de dia, "
    "el agua en calma aparece oscura) y menciona que NISAR (banda L) ampliara esta capacidad."
)


def _resumen_stats(stats: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in stats.items())


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


def generar_informe_stream(nombre: str, descripcion: str, stats: dict):
    """
    Generador de trozos de texto (compatible con st.write_stream).
    Lanza RuntimeError si no hay API key; otras excepciones de red se propagan.
    """
    api_key = os.getenv("MODELSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno MODELSCOPE_API_KEY")

    from openai import OpenAI  # import tardio: la app arranca aunque falte el paquete

    client = OpenAI(base_url=BASE_URL, api_key=api_key)
    user_msg = (
        f"Caso: {nombre}\n"
        f"Contexto: {descripcion or 'sin descripcion'}\n"
        f"Datos medidos:\n{_resumen_stats(stats)}\n\n"
        "Redacta el informe."
    )
    # Los modelos Omni suelen exigir stream=True
    stream = client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content