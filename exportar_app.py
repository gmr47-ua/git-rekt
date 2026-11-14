"""
exportar_app.py - Puente entre procedimiento.py y app.py.

Lee la carpeta de resultados de procedimiento.py y deja lista data/<caso>/:
    results.json, mascara_agua.tif, antes.png, despues.png, resumen.png

Uso:
    py procedimiento.py --sin-ventana
    py exportar_app.py resultados data/valencia

Las metricas (area, perimetro, compactacion, elongacion, momentos de Hu,
centroide) se calculan en una cuadricula METRICA (UTM, 10 m) para que las
unidades sean reales. Si el results.json ya existe, se conservan sus otras
claves (p. ej. las de poblacion.py).
"""
import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import (Resampling, calculate_default_transform, reproject,
                           transform as transformar, transform_bounds)
from scipy import ndimage

# ---- Textos editables ------------------------------------------------
LIMITACIONES = [
    "No representa toda la extensión de la imagen óptica ni toda la Albufera.",
    "No representa la inundación máxima de la DANA ni una superficie oficialmente afectada.",
    "Las superficies oscuras previas se excluyen como aproximación; no constituyen agua permanente confirmada.",
    "Los cambios agrícolas, humedad y sombras pueden producir falsos positivos; agua urbana o bajo vegetación puede omitirse.",
    "Las métricas describen todas las zonas candidatas agregadas, no el municipio de Paiporta.",
]
DB_MIN, DB_MAX, GRIS_SIN_DATO = -25.0, 0.0, 220


# ---- Cuadricula metrica ---------------------------------------------
def a_cuadricula_metrica(agua, crs, transform, res=10.0):
    """Devuelve (mascara bool, transform, res_x, res_y) en un CRS proyectado."""
    if crs.is_projected:
        return agua, transform, abs(transform.a), abs(transform.e), crs
    alto, ancho = agua.shape
    o, s, e, n = rasterio.transform.array_bounds(alto, ancho, transform)
    zona = int(math.floor(((o + e) / 2 + 180) / 6) + 1)
    epsg = (32600 if (s + n) / 2 >= 0 else 32700) + zona
    destino_crs = CRS.from_epsg(epsg)
    t, w, h = calculate_default_transform(crs, destino_crs, ancho, alto, o, s, e, n, resolution=res)
    salida = np.zeros((h, w), dtype="uint8")
    reproject(agua.astype("uint8"), salida, src_transform=transform, src_crs=crs,
              dst_transform=t, dst_crs=destino_crs, resampling=Resampling.nearest)
    return salida > 0, t, abs(t.a), abs(t.e), destino_crs


# ---- Metricas -------------------------------------------------------
def perimetro_aristas(m, res):
    """Suma de bordes expuestos de pixeles (incluye huecos y componentes separados)."""
    p = np.pad(m, 1, constant_values=False)
    c = p[1:-1, 1:-1]
    aristas = ((c & ~p[:-2, 1:-1]).sum() + (c & ~p[2:, 1:-1]).sum()
               + (c & ~p[1:-1, :-2]).sum() + (c & ~p[1:-1, 2:]).sum())
    return float(aristas) * res


def elongacion(ys, xs, rx, ry):
    cov = np.cov(np.vstack([xs * rx, ys * ry]))
    v = np.sort(np.linalg.eigvalsh(cov))
    return float(math.sqrt(max(v[0], 0) / v[1])) if v[1] > 0 else None


def momentos_hu(ys, xs):
    """Siete momentos de Hu de la mascara binaria (valores brutos)."""
    ys, xs = ys.astype("float64"), xs.astype("float64")
    m00 = len(xs)
    dx, dy = xs - xs.mean(), ys - ys.mean()

    def eta(p, q):
        return np.sum(dx ** p * dy ** q) / m00 ** (1 + (p + q) / 2)

    n20, n02, n11 = eta(2, 0), eta(0, 2), eta(1, 1)
    n30, n03, n21, n12 = eta(3, 0), eta(0, 3), eta(2, 1), eta(1, 2)
    a, b = n30 + n12, n21 + n03
    return [
        n20 + n02,
        (n20 - n02) ** 2 + 4 * n11 ** 2,
        (n30 - 3 * n12) ** 2 + (3 * n21 - n03) ** 2,
        a ** 2 + b ** 2,
        (n30 - 3 * n12) * a * (a ** 2 - 3 * b ** 2) + (3 * n21 - n03) * b * (3 * a ** 2 - b ** 2),
        (n20 - n02) * (a ** 2 - b ** 2) + 4 * n11 * a * b,
        (3 * n21 - n03) * a * (a ** 2 - 3 * b ** 2) - (n30 - 3 * n12) * b * (3 * a ** 2 - b ** 2),
    ]


# ---- PNG ------------------------------------------------------------
def tif_db_a_png(ruta_tif, ruta_png, max_lado=2000):
    with rasterio.open(ruta_tif) as s:
        db = s.read(1, masked=True).astype("float64").filled(np.nan)
    gris = (np.nan_to_num(np.clip((db - DB_MIN) / (DB_MAX - DB_MIN), 0, 1)) * 255).astype(np.uint8)
    gris[~np.isfinite(db)] = GRIS_SIN_DATO
    im = Image.fromarray(gris, mode="L")
    im.thumbnail((max_lado, max_lado))
    im.save(ruta_png, optimize=True)


# ---- Principal ------------------------------------------------------
def main(resultados, destino, nombre, descripcion, sensor, pol, f_antes, f_despues):
    resultados, destino = Path(resultados), Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    with rasterio.open(resultados / "mascara_inundacion.tif") as src:
        datos = src.read(1)
        crs, transform = src.crs, src.transform
    agua = datos == 1                    # 255 = sin dato, 0 = no agua
    validos = datos != 255
    if not agua.any():
        raise ValueError("La mascara no contiene ningun pixel de agua.")

    # Mascara limpia 0/1 (sin nodata) para la app
    with rasterio.open(destino / "mascara_agua.tif", "w", driver="GTiff",
                       height=agua.shape[0], width=agua.shape[1], count=1, dtype="uint8",
                       crs=crs, transform=transform, compress="deflate") as dst:
        dst.write(agua.astype("uint8"), 1)

    # Metricas en cuadricula metrica
    m, t, rx, ry, crs_m = a_cuadricula_metrica(agua, crs, transform)
    ys, xs = np.nonzero(m)
    area_m2 = len(xs) * rx * ry
    perim = perimetro_aristas(m, rx)
    cx, cy = t.c + (xs.mean() + 0.5) * t.a, t.f + (ys.mean() + 0.5) * t.e
    lon, lat = transformar(crs_m, "EPSG:4326", [cx], [cy])
    _, n_comp = ndimage.label(m, structure=np.ones((3, 3)))

    nuevos = {
        "nombre": nombre, "descripcion": descripcion, "sensor": sensor,
        "polarizacion": pol, "fecha_antes": f_antes, "fecha_despues": f_despues,
        "hectareas_afectadas": round(area_m2 / 10_000, 2),
        "perimetro": round(perim, 1),
        "compactacion": 4 * math.pi * area_m2 / perim ** 2 if perim else None,
        "elongacion": elongacion(ys, xs, rx, ry),
        "momentos_hu": momentos_hu(ys, xs),
        "centroide": {"lat": lat[0], "lon": lon[0]},
        "estado": "deteccion_exploratoria_no_validada",
        "pixeles_candidatos_originales": int(agua.sum()),
        "pixeles_validos_originales": int(validos.sum()),
        "porcentaje_candidato_original": 100 * float(agua.sum()) / float(validos.sum()),
        "componentes_en_cuadricula_metrica": int(n_comp),
        "limitaciones": LIMITACIONES,
    }
    est = resultados / "estadisticas.json"
    if est.exists():
        e = json.loads(est.read_text(encoding="utf-8"))
        nuevos["parametros"] = {
            "agua_db": e.get("agua_db"), "caida_db": e.get("caida_db"),
            "filtro_media_lineal": e.get("filtro"), "min_pixeles": e.get("min_pixeles"),
            "conectividad": 8,
        }

    ruta_json = destino / "results.json"
    previo = json.loads(ruta_json.read_text(encoding="utf-8")) if ruta_json.exists() else {}
    previo.update(nuevos)
    for k in ("poblacion_afectada", "fiabilidad"):     # solo si no existen ya
        previo.setdefault(k, None)
    ruta_json.write_text(json.dumps(previo, indent=2, ensure_ascii=False), encoding="utf-8")

    # Imagenes para el slider y el resumen
    tif_db_a_png(resultados / "antes_filtrado_db.tif", destino / "antes.png")
    tif_db_a_png(resultados / "despues_filtrado_db.tif", destino / "despues.png")
    resumen = resultados / "resumen_inundacion.png"
    if resumen.exists():
        shutil.copy(resumen, destino / "resumen.png")

    print(f"Listo: {destino}")
    print(f"  Area: {nuevos['hectareas_afectadas']} ha | manchas: {n_comp} | "
          f"% escena: {nuevos['porcentaje_candidato_original']:.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("resultados", help="carpeta de salida de procedimiento.py")
    ap.add_argument("destino", help="p.ej. data/valencia")
    ap.add_argument("--nombre", default="Posible inundación en Valencia y norte de la Albufera")
    ap.add_argument("--descripcion", default=None)
    ap.add_argument("--sensor", default="Sentinel-1 (banda C)")
    ap.add_argument("--polarizacion", default="VV")
    ap.add_argument("--fecha-antes", default="2024-10-19")
    ap.add_argument("--fecha-despues", default="2024-10-31")
    a = ap.parse_args()
    desc = a.descripcion or (
        f"Detección exploratoria de posible agua nueva en toda la cobertura común de los "
        f"GeoTIFF del {a.fecha_antes} y {a.fecha_despues}; no limitada a Paiporta."
    )
    main(a.resultados, a.destino, a.nombre, desc, a.sensor, a.polarizacion,
         a.fecha_antes, a.fecha_despues)
