import numpy as np
import rasterio

# Creamos una matriz de 100x100 con valores aleatorios (simulando ruido de radar)
matriz_antes = np.random.rand(100, 100).astype(np.float32) * 10
matriz_despues = matriz_antes.copy()

# Simulamos una bajada brusca de retrodispersión (agua) en el centro (zona de 20x20)
matriz_despues[40:60, 40:60] = 0.5

# Metadatos geográficos básicos para rasterio
transform = rasterio.transform.from_origin(
    0, 0, 10, 10
)  # píxeles de 10x10 metros
meta = {
    "driver": "GTiff",
    "height": 100,
    "width": 100,
    "count": 1,
    "dtype": "float32",
    "crs": "+proj=latlong",
    "transform": transform,
}

# Guardamos los archivos falsos con los nombres que espera el script
with rasterio.open("before_sigma0.tiff", "w", **meta) as dst:
  dst.write(matriz_antes, 1)

with rasterio.open("after_sigma0.tiff", "w", **meta) as dst:
  dst.write(matriz_despues, 1)

print(
    "¡Imágenes falsas generadas con éxito: 'before_sigma0.tiff' y"
    " 'after_sigma0.tiff'!"
)