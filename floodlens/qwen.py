import os
import sys

from openai import OpenAI
from dotenv import load_dotenv
# Carga automática del archivo .env ubicado en el mismo directorio
load_dotenv()

BASE_URL = os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.ai/v1")
MODEL_ID = os.getenv("MODELSCOPE_MODEL", "Qwen-Ambassador/Qwen3.8-Omni-Flash")
api_key = os.getenv("MODELSCOPE_API_KEY")
if not api_key:

    sys.exit("Falta la variable de entorno MODELSCOPE_API_KEY")
prompt = " ".join(sys.argv[1:]) or "Hola, presentate en una frase."
client = OpenAI(base_url=BASE_URL, api_key=api_key)
# Los modelos Omni suelen exigir stream=True
stream = client.chat.completions.create(
    model=MODEL_ID,
    messages=[{"role": "user", "content": prompt}],
    stream=True,
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()