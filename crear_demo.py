"""
crear_demo.py - Genera un caso de prueba sintetico en data/demo/
(NO son datos reales; solo sirve para comprobar que app.py funciona).

Uso:  python crear_demo.py
"""
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin

carpeta = Path("data") / "demo"
carpeta.mkdir(parents=True, exist_ok=True)

N = 400
rng = np.random.default_rng(42)

# Mascara: una "mancha" alargada de agua
yy, xx = np.mgrid[0:N, 0:N]
mascara = (((xx - 200) / 130) ** 2 + ((yy - 200) / 45) ** 2 < 1).astype(np.uint8)

# Imagenes sigma0 sinteticas con ruido speckle; el agua se oscurece despues
base = rng.gamma(4.0, 0.06, (N, N))
antes = base.copy()
despues = base.copy()
despues[mascara == 1] *= 0.12


def a_png(arr, ruta):
    img = np.clip(arr / np.percentile(arr, 99), 0, 1)
    Image.fromarray((img * 255).astype(np.uint8)).save(ruta)


a_png(antes, carpeta / "antes.png")
a_png(despues, carpeta / "despues.png")

# GeoTIFF en UTM 30N (EPSG:32630) alrededor de Valencia, pixeles de 30 m
transform = from_origin(715000, 4380000, 30, 30)
with rasterio.open(
    carpeta / "mascara_agua.tif", "w", driver="GTiff", height=N, width=N,
    count=1, dtype="uint8", crs="EPSG:32630", transform=transform,
) as dst:
    dst.write(mascara, 1)

area_ha = float(mascara.sum()) * 30 * 30 / 10_000
resultados = {
    "nombre": "Caso de prueba (datos sintéticos)",
    "descripcion": "Mancha de agua simulada para probar la interfaz.",
    "sensor": "SINTÉTICO - solo pruebas",
    "hectareas_afectadas": round(area_ha, 1),
    "perimetro": 1480.0,
    "compactacion": 0.62,
    "elongacion": 0.71,
    "momentos_hu": [0.19, 0.01, 0.0003, 0.0001, 0.0, 0.0, 0.0],
    "centroide": {"lat": 39.55, "lon": -0.45},
}
with open(carpeta / "results.json", "w", encoding="utf-8") as f:
    json.dump(resultados, f, indent=2, ensure_ascii=False)

print(f"Caso de prueba creado en {carpeta}  ({area_ha:.0f} ha de agua   simulada)")
