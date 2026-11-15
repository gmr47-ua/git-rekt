
"""
exportar_nisar.py - Prepara las imagenes NISAR para la app (comparativa antes/despues).
 
Lee dos GeoTIFF de NISAR (gamma0 lineal, HH) y deja en data/<caso>/:
    nisar_antes.png, nisar_despues.png, nisar.json, nisar_mascara_agua.tif
(la mascara es "posible agua nueva", con la misma logica que procedimiento.py)
 
Uso:
    py exportar_nisar.py Valencia_NISAR_20261004_HH_gamma0_lineal_recorte_1_.tif ^
                         Valencia_NISAR_20261016_HH_gamma0_lineal_recorte.tif data/valencia
 
La fecha se saca del nombre del archivo (el bloque de 8 digitos AAAAMMDD);
si no la encuentra, usa --fecha-antes / --fecha-despues.
"""
import argparse
import json
import re
from pathlib import Path
 
import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import transform as transformar
from scipy import ndimage
 
DB_MIN, DB_MAX, GRIS_SIN_DATO = -30.0, 0.0, 220  # mismo rango que la figura de procedimiento
 
 
def fecha_del_nombre(ruta: Path):
    """Busca AAAAMMDD en el nombre y lo devuelve como AAAA-MM-DD (o None)."""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", ruta.name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
 
 
def poligono_wgs84(ruta_tif: Path):
    """Las 4 esquinas de la imagen en [lat, lon]. Se transforman las esquinas (no solo
    los limites) porque un rectangulo en UTM queda ligeramente girado en lat/lon."""
    with rasterio.open(ruta_tif) as s:
        o, so, e, n = s.bounds
        xs, ys = [o, e, e, o], [n, n, so, so]
        lons, lats = transformar(s.crs, "EPSG:4326", xs, ys)
    return [[round(la, 6), round(lo, 6)] for la, lo in zip(lats, lons)]
 
 
def leer_lineal(ruta: Path):
    """Lee gamma0 lineal; los valores no validos (<=0, NaN, sin dato) pasan a NaN."""
    with rasterio.open(ruta) as s:
        a = s.read(1).astype("float32")
        validos = s.read_masks(1) > 0
        perfil = s.profile.copy()
    a[~(validos & np.isfinite(a) & (a > 0))] = np.nan
    return a, perfil
 
 
def media_local(a, tam):
    """Media local en potencia LINEAL sin contaminar con NoData (igual que procedimiento.py)."""
    v = np.isfinite(a)
    peso = ndimage.uniform_filter(v.astype("float32"), size=tam, mode="constant")
    suma = ndimage.uniform_filter(np.where(v, a, 0), size=tam, mode="constant")
    return np.divide(suma, peso, out=np.full_like(a, np.nan), where=peso > 0)
 
 
def limpiar(m, minimo):
    """Quita grupos de menos de 'minimo' pixeles (conectividad 8)."""
    etiquetas, _ = ndimage.label(m, structure=np.ones((3, 3)))
    conservar = np.bincount(etiquetas.ravel()) >= minimo
    conservar[0] = False
    return conservar[etiquetas]
 
 
def detectar_agua_nueva(ruta_antes, ruta_despues, ruta_salida, filtro=3, agua_db=-17.0,
                        caida_db=-3.0, minimo=25):
    """Agua nueva = oscura DESPUES (< agua_db), no oscura ANTES, y con una caida >= |caida_db|."""
    antes, perfil = leer_lineal(ruta_antes)
    despues, perfil_d = leer_lineal(ruta_despues)
    if (antes.shape != despues.shape or perfil["crs"] != perfil_d["crs"]
            or perfil["transform"] != perfil_d["transform"]):
        raise ValueError("Las dos imagenes NISAR no comparten cuadricula; hay que alinearlas antes.")
    validos = np.isfinite(antes) & np.isfinite(despues)
    with np.errstate(divide="ignore", invalid="ignore"):
        b = 10 * np.log10(media_local(antes, filtro))
        a = 10 * np.log10(media_local(despues, filtro))
    b[~validos] = np.nan
    a[~validos] = np.nan
    cambio = a - b
    previa = limpiar(validos & (b < agua_db), minimo)
    candidata = validos & ~previa & (a < agua_db) & (cambio <= caida_db)
    nueva = limpiar(candidata, minimo)
 
    mascara = np.where(validos, nueva.astype("uint8"), 255).astype("uint8")  # 255 = sin dato
    with rasterio.open(ruta_salida, "w", driver="GTiff", height=mascara.shape[0],
                       width=mascara.shape[1], count=1, dtype="uint8", crs=perfil["crs"],
                       transform=perfil["transform"], nodata=255, compress="deflate") as dst:
        dst.write(mascara, 1)
    res_x, res_y = abs(perfil["transform"].a), abs(perfil["transform"].e)
    return {
        "hectareas_afectadas": round(float(nueva.sum()) * res_x * res_y / 10_000, 2),
        "pixeles_candidatos": int(nueva.sum()),
        "pixeles_validos": int(validos.sum()),
        "parametros": {"agua_db": agua_db, "caida_db": caida_db, "filtro": filtro, "min_pixeles": minimo},
    }
 
 
def tif_a_png(ruta_tif: Path, ruta_png: Path, filtro=3, max_lado=2000):
    with rasterio.open(ruta_tif) as s:
        lineal = s.read(1).astype("float32")
        validos = s.read_masks(1) > 0
    validos &= np.isfinite(lineal) & (lineal > 0)
 
    # Media local EN LINEAL (no en dB) y sin contaminar con NoData: es lo que hace
    # procedimiento.py. Reduce el speckle sin falsear la potencia.
    if filtro > 1:
        peso = ndimage.uniform_filter(validos.astype("float32"), size=filtro, mode="constant")
        suma = ndimage.uniform_filter(np.where(validos, lineal, 0), size=filtro, mode="constant")
        lineal = np.divide(suma, peso, out=np.full_like(lineal, np.nan), where=peso > 0)
        validos &= np.isfinite(lineal) & (lineal > 0)
 
    db = np.full(lineal.shape, np.nan, dtype="float32")
    db[validos] = 10 * np.log10(lineal[validos])
    gris = (np.clip((db - DB_MIN) / (DB_MAX - DB_MIN), 0, 1) * 255).astype(np.uint8)
    gris[~validos] = GRIS_SIN_DATO
    im = Image.fromarray(gris, mode="L")
    im.thumbnail((max_lado, max_lado))
    im.save(ruta_png, optimize=True)
 
 
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("antes", type=Path)
    ap.add_argument("despues", type=Path)
    ap.add_argument("destino", type=Path, help="p.ej. data/valencia")
    ap.add_argument("--fecha-antes")
    ap.add_argument("--fecha-despues")
    ap.add_argument("--filtro", type=int, default=3, help="tamano del filtro de media (impar, 1 = sin filtro)")
    ap.add_argument("--agua-db", type=float, default=-17.0, help="umbral de agua (dB)")
    ap.add_argument("--caida-db", type=float, default=-3.0, help="caida minima de senal (dB, negativa)")
    ap.add_argument("--min-pixeles", type=int, default=25, help="tamano minimo de mancha")
    a = ap.parse_args()
 
    f_a = a.fecha_antes or fecha_del_nombre(a.antes)
    f_d = a.fecha_despues or fecha_del_nombre(a.despues)
    if not (f_a and f_d):
        ap.error("No pude sacar las fechas del nombre; pasalas con --fecha-antes y --fecha-despues.")
 
    a.destino.mkdir(parents=True, exist_ok=True)
    tif_a_png(a.antes, a.destino / "nisar_antes.png", a.filtro)
    tif_a_png(a.despues, a.destino / "nisar_despues.png", a.filtro)
 
    deteccion = detectar_agua_nueva(a.antes, a.despues, a.destino / "nisar_mascara_agua.tif",
                                    a.filtro, a.agua_db, a.caida_db, a.min_pixeles)
 
    meta = {
        "sensor": "NISAR (banda L)",
        "polarizacion": "HH",
        "producto": "gamma0 lineal",
        "fecha_antes": f_a,
        "fecha_despues": f_d,
        "poligono_wgs84": poligono_wgs84(a.antes),
        "escala_db": [DB_MIN, DB_MAX],
        "filtro_media_lineal": a.filtro,
        "deteccion": deteccion,
        "estado": "deteccion_exploratoria_no_validada",
    }
    (a.destino / "nisar.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {a.destino}  ({f_a} -> {f_d})")
    print(f"  Agua nueva NISAR: {deteccion['hectareas_afectadas']} ha "
          f"({deteccion['pixeles_candidatos']} px de {deteccion['pixeles_validos']} validos)")
 