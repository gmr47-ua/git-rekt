#!/usr/bin/env python3
"""
FloodyLens - procesamiento.py (version final)

Detecta agua nueva (inundacion) comparando dos escenas SAR (antes / despues).

Entradas : dos GeoTIFF de sigma0 de la misma polarizacion (lineal o dB)
Salidas  (en --salida):
    water_level.tif           mascara multiclase: 0 nada | 1 agua nueva | 2 aumento | 255 sin datos
    diferencia_db.tif         cambio de retrodispersion (despues - antes), en dB
    results.json              estadisticas, descriptores por mancha, sensibilidad, limites
    resultados.geojson        un poligono por mancha (listo para un mapa web)
    mascara_web.png           capa RGBA ligera de la mascara (para ImageOverlay)
    diferencia_web.png        capa RGBA ligera de la diferencia en dB
    vista_previa_mascara.png  vista rapida en color para revisar el resultado

Uso:
    python procesamiento.py --antes 19_octubre.tif --despues 31_octubre.tif \
        --fecha-antes 2024-10-19 --fecha-despues 2024-10-31
    python procesamiento.py --help

Dependencias: pip install -r requirements.txt
"""

import argparse
import json
import math
import os
import sys

import cv2 as cv
import numpy as np
import rasterio
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, reproject, transform as warp_transform, transform_bounds

CLASE_NADA, CLASE_AGUA, CLASE_AUMENTO, CLASE_NODATA = 0, 1, 2, 255


# ==========================================================================
# ARGUMENTOS
# ==========================================================================
def parse_args():
    p = argparse.ArgumentParser(
        description="FloodyLens: deteccion de agua nueva con SAR (antes/despues).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--antes", default="19_octubre.tif", help="escena previa")
    p.add_argument("--despues", default="31_octubre.tif", help="escena posterior")
    p.add_argument("--fecha-antes", default=None, help="fecha de la escena previa (p. ej. 2024-10-19)")
    p.add_argument("--fecha-despues", default=None, help="fecha de la escena posterior")
    p.add_argument("--salida", default=".", help="carpeta de salida")

    p.add_argument("--umbral", type=float, default=-3.0,
                   help="caida minima de sigma0 en dB para marcar agua nueva")
    p.add_argument("--agua-max", type=float, default=-15.0,
                   help="sigma0 maximo (dB) en la escena posterior para ser agua; 999 desactiva")
    p.add_argument("--umbral-aumento", type=float, default=5.0,
                   help="aumento minimo en dB para la clase 2 (doble rebote)")
    p.add_argument("--normalizar-mediana", action="store_true",
                   help="resta la mediana de la diferencia (umbrales relativos al nivel normal)")

    p.add_argument("--mediana-ksize", type=int, choices=[3, 5], default=5, help="filtro de speckle")
    p.add_argument("--kernel", type=int, default=3, help="kernel morfologico en px (1 = sin limpieza)")
    p.add_argument("--area-min", type=int, default=100, help="area minima (px) de una mancha de agua")
    p.add_argument("--area-min-aumento", type=int, default=300, help="area minima (px) clase 2")
    p.add_argument("--top", type=int, default=20, help="manchas a detallar por clase")

    p.add_argument("--sin-filtro-mar", action="store_true",
                   help="desactiva el filtro de manchas grandes pegadas al borde")
    p.add_argument("--mar-frac", type=float, default=0.02,
                   help="fraccion de la escena a partir de la cual una mancha de borde es mar")
    p.add_argument("--agua-permanente", default=None,
                   help="GeoTIFF de agua permanente (JRC / WorldCover) a excluir")
    p.add_argument("--agua-perm-min", type=float, default=0.5,
                   help="umbral sobre esa capa: 0.5 si es binaria, 50 si es 'occurrence' de JRC")
    p.add_argument("--agua-perm-buffer", type=int, default=3, help="margen (px) alrededor del agua permanente")

    p.add_argument("--sin-sensibilidad", action="store_true", help="omite el analisis de sensibilidad")
    p.add_argument("--sensibilidad", type=float, nargs="+", default=[-2.0, -3.0, -4.0, -5.0],
                   help="umbrales (dB) para el analisis de sensibilidad")
    a = p.parse_args()
    if a.agua_max >= 999:
        a.agua_max = None
    return a


# ==========================================================================
# LECTURA Y ALINEACION
# ==========================================================================
def _leer(ruta):
    """Banda 1 como float32 con NaN en nodata."""
    with rasterio.open(ruta) as src:
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None and not np.isnan(src.nodata):
            arr[arr == src.nodata] = np.nan
        meta = src.meta.copy()
        transform, crs = src.transform, src.crs
    arr[~np.isfinite(arr)] = np.nan
    return arr, meta, transform, crs


def _alinear(ruta, meta_dest, metodo=Resampling.bilinear):
    """Reproyecta/remuestrea 'ruta' a la malla de meta_dest. Los 0 (nodata de SNAP) no se mezclan."""
    with rasterio.open(ruta) as src:
        dest = np.full((meta_dest["height"], meta_dest["width"]), np.nan, np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dest,
            src_nodata=src.nodata if src.nodata is not None else 0,
            dst_nodata=np.nan,
            dst_transform=meta_dest["transform"],
            dst_crs=meta_dest["crs"],
            resampling=metodo,
        )
    return dest


def cargar_escenas(ruta_antes, ruta_despues):
    antes, meta, tr_a, crs_a = _leer(ruta_antes)
    despues, _, tr_d, crs_d = _leer(ruta_despues)
    if antes.shape != despues.shape or tr_a != tr_d or crs_a != crs_d:
        print("Aviso: las escenas no comparten malla; se remuestrea 'despues' a la de 'antes'.")
        despues = _alinear(ruta_despues, meta)
    return antes, despues, meta


def normalizar_a_db(a):
    """Devuelve (array en dB, fue_lineal). Ceros y negativos en lineal -> NaN."""
    validos = a[np.isfinite(a)]
    if validos.size == 0:
        raise ValueError("La imagen no contiene pixeles validos.")
    if np.mean(validos < 0) < 0.01 and np.percentile(validos, 99) < 10:
        lin = a.copy()
        lin[lin <= 0] = np.nan
        return 10.0 * np.log10(lin), True
    out = a.copy()
    out[out == 0] = np.nan
    return out, False


# ==========================================================================
# GEOMETRIA
# ==========================================================================
def pixel_area(meta):
    """(m2 por pixel, metros por pixel) para CRS proyectado o geografico."""
    t, crs = meta["transform"], meta["crs"]
    px, py = abs(t.a), abs(t.e)
    if crs is not None and crs.is_geographic:
        lat = t.f + t.e * meta["height"] / 2.0
        mx = 111_320.0 * math.cos(math.radians(lat)) * px
        my = 110_574.0 * py
        return mx * my, (mx + my) / 2.0
    return px * py, (px + py) / 2.0


def px_to_lonlat(meta, cols, rows):
    """Coordenadas de pixel -> (lon, lat) WGS84."""
    xs, ys = [], []
    for c, r in zip(cols, rows):
        x, y = meta["transform"] * (c + 0.5, r + 0.5)
        xs.append(x)
        ys.append(y)
    crs = meta["crs"]
    if crs is not None and not (crs.is_geographic and crs.to_epsg() == 4326):
        xs, ys = warp_transform(crs, "EPSG:4326", xs, ys)
    return [float(v) for v in xs], [float(v) for v in ys]


def limites_wgs84(meta):
    oeste, sur, este, norte = array_bounds(meta["height"], meta["width"], meta["transform"])
    crs = meta["crs"]
    if crs is not None and not (crs.is_geographic and crs.to_epsg() == 4326):
        oeste, sur, este, norte = transform_bounds(crs, "EPSG:4326", oeste, sur, este, norte)
    return {"sur": float(sur), "oeste": float(oeste), "norte": float(norte), "este": float(este)}


# ==========================================================================
# DESCRIPTORES MORFOLOGICOS
# ==========================================================================
def _hu_log(Hu):
    out = []
    for h in Hu:
        if h == 0 or not np.isfinite(h):
            out.append(0.0)
        else:
            out.append(float(-math.copysign(1.0, h) * math.log10(abs(h))))
    return out


def Descriptors(contour):
    """
    Descriptores de UN contorno (unidades de pixel). None si es degenerado.
      compactacion : P^2 / (4*pi*A)   (1 = circulo, mayor = mas irregular)
      elongacion   : lado mayor / lado menor del rectangulo minimo rotado (>= 1)
    """
    area = cv.contourArea(contour)
    perimetro = cv.arcLength(contour, True)
    if area <= 0 or perimetro <= 0:
        return None
    d = {
        "area_px": float(area),
        "perimetro_px": float(perimetro),
        "compactacion": float(perimetro ** 2 / (4 * math.pi * area)),
    }
    (_, _), (rw, rh), _ = cv.minAreaRect(contour)
    lado_max, lado_min = max(rw, rh), min(rw, rh)
    d["elongacion"] = float(lado_max / lado_min) if lado_min > 0 else None
    d["rectangularidad"] = float(area / (rw * rh)) if rw * rh > 0 else 0.0

    hull_area = cv.contourArea(cv.convexHull(contour))
    d["solidez"] = float(area / hull_area) if hull_area > 0 else None

    M = cv.moments(contour)
    if M["m00"] != 0:
        d["centroide_px"] = [float(M["m10"] / M["m00"]), float(M["m01"] / M["m00"])]
        d["orientacion_grados"] = float(math.degrees(0.5 * math.atan2(2 * M["mu11"], M["mu20"] - M["mu02"])))
        d["Hu"] = _hu_log(cv.HuMoments(M).flatten())
    else:
        x, y, w, h = cv.boundingRect(contour)
        d["centroide_px"] = [float(x + w / 2), float(y + h / 2)]
        d["orientacion_grados"] = 0.0
        d["Hu"] = [0.0] * 7
    return d


def analizar_mascara(mascara, meta, top_n):
    """Estadisticas globales + descriptores de las 'top_n' manchas mas grandes."""
    n_px = int(mascara.sum())
    if n_px == 0:
        return None
    m2_px, m_px = pixel_area(meta)

    M = cv.moments(mascara, binaryImage=True)
    lon_c, lat_c = px_to_lonlat(meta, [M["m10"] / M["m00"]], [M["m01"] / M["m00"]])
    area_ha = n_px * m2_px / 10_000.0

    contornos, _ = cv.findContours(mascara, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    contornos = sorted(contornos, key=cv.contourArea, reverse=True)

    regiones = []
    for c in contornos:
        if len(regiones) >= top_n:
            break
        d = Descriptors(c)
        if d is None:
            continue
        lon, lat = px_to_lonlat(meta, [d["centroide_px"][0]], [d["centroide_px"][1]])

        poly = cv.approxPolyDP(c, 2.0, True).reshape(-1, 2)
        if len(poly) < 3:
            poly = c.reshape(-1, 2)
        poligono = None
        if len(poly) >= 3:
            plon, plat = px_to_lonlat(meta, poly[:, 0].tolist(), poly[:, 1].tolist())
            poligono = [[a, b] for a, b in zip(plon, plat)]

        regiones.append({
            "id": len(regiones) + 1,
            "area_ha": round(d["area_px"] * m2_px / 10_000.0, 3),
            "perimetro_m": round(d["perimetro_px"] * m_px, 2),
            "compactacion": d["compactacion"],
            "elongacion": d["elongacion"],
            "rectangularidad": d["rectangularidad"],
            "solidez": d["solidez"],
            "orientacion_grados": d["orientacion_grados"],
            "Hu": d["Hu"],
            "centroide": {"lon": lon[0], "lat": lat[0]},
            "poligono_lonlat": poligono,   # [lon, lat]; anillo sin cerrar
        })
    return {
        "global": {
            "pixeles": n_px,
            "area_ha": round(area_ha, 3),
            "area_km2": round(area_ha / 100.0, 4),
            "num_manchas": len(contornos),
            "centroide": {"lon": lon_c[0], "lat": lat_c[0]},
        },
        "regiones": regiones,
    }


# ==========================================================================
# MASCARAS
# ==========================================================================
def limpiar(mascara, kernel_px):
    if kernel_px > 1:
        k = cv.getStructuringElement(cv.MORPH_ELLIPSE, (kernel_px, kernel_px))
        mascara = cv.morphologyEx(mascara, cv.MORPH_OPEN, k)
        mascara = cv.morphologyEx(mascara, cv.MORPH_CLOSE, k)
    return mascara


def quitar_pequenas(mascara, area_min):
    n, lab, stats, _ = cv.connectedComponentsWithStats(mascara, connectivity=8)
    if n <= 1:
        return mascara
    pequenas = np.nonzero(stats[1:, cv.CC_STAT_AREA] < area_min)[0] + 1
    if len(pequenas):
        mascara[np.isin(lab, pequenas)] = 0
    return mascara


def quitar_mar(mascara, valid, frac, verbose=True):
    """
    Elimina manchas grandes pegadas al borde de la imagen o de la zona sin datos.
    Es un parche: lo robusto es --agua-permanente. Ojo: una inundacion real
    pegada a la costa tambien se borraria.
    """
    h, w = mascara.shape
    n, lab, stats, _ = cv.connectedComponentsWithStats(mascara, connectivity=8)
    if n <= 1:
        return mascara
    zona = cv.dilate((~valid).astype(np.uint8), np.ones((5, 5), np.uint8))
    zona[0, :] = zona[-1, :] = 1
    zona[:, 0] = zona[:, -1] = 1
    en_borde = set(np.unique(lab[zona > 0]).tolist()) - {0}
    eliminar = [i for i in en_borde if stats[i, cv.CC_STAT_AREA] > frac * h * w]
    if eliminar:
        mascara[np.isin(lab, eliminar)] = 0
    if verbose:
        print(f"Filtro de mar: {len(eliminar)} mancha(s) grande(s) de borde eliminada(s)")
    return mascara


def cargar_agua_permanente(meta, a):
    if not a.agua_permanente:
        return None
    try:
        arr = _alinear(a.agua_permanente, meta, Resampling.nearest)
    except rasterio.errors.RasterioIOError as e:
        print(f"Aviso: no se pudo abrir la mascara de agua permanente ({e}). Se ignora.")
        return None
    perm = np.nan_to_num(arr, nan=0.0) > a.agua_perm_min
    if a.agua_perm_buffer > 0:
        k = np.ones((2 * a.agua_perm_buffer + 1,) * 2, np.uint8)
        perm = cv.dilate(perm.astype(np.uint8), k) > 0
    print(f"Agua permanente excluida: {perm.mean() * 100:.2f}% de la escena")
    return perm


def detectar_caida(diferencia, despues_s, valid, perm, a, umbral=None, verbose=True):
    """Clase 1: caida de retrodispersion + 'despues' oscuro (superficie lisa)."""
    umbral = a.umbral if umbral is None else umbral
    cond = diferencia < umbral
    if a.agua_max is not None:
        cond &= despues_s < a.agua_max
    m = (cond & valid).astype(np.uint8)
    if perm is not None:
        m[perm] = 0
    m = limpiar(m, a.kernel)
    if not a.sin_filtro_mar:
        m = quitar_mar(m, valid, a.mar_frac, verbose)
    return quitar_pequenas(m, a.area_min)


def detectar_aumento(diferencia, valid, perm, a):
    """Clase 2: aumento de retrodispersion (doble rebote: urbano / vegetacion inundada)."""
    m = ((diferencia > a.umbral_aumento) & valid).astype(np.uint8)
    if perm is not None:
        m[perm] = 0
    m = limpiar(m, a.kernel)
    if not a.sin_filtro_mar:
        m = quitar_mar(m, valid, a.mar_frac)
    return quitar_pequenas(m, a.area_min_aumento)


def analisis_sensibilidad(diferencia, despues_s, valid, perm, a, m2_px):
    res = []
    for u in a.sensibilidad:
        m = detectar_caida(diferencia, despues_s, valid, perm, a, umbral=u, verbose=False)
        n = int(m.sum())
        res.append({"umbral_db": u, "pixeles": n, "area_ha": round(n * m2_px / 10_000.0, 1)})
        print(f"  umbral {u:+.1f} dB -> {res[-1]['area_ha']} ha")
    return res


# ==========================================================================
# SALIDAS
# ==========================================================================
def guardar_tif(ruta, arr, meta, dtype, nodata):
    m = meta.copy()
    m.update(dtype=dtype, count=1, nodata=nodata, compress="lzw")
    with rasterio.open(ruta, "w", **m) as dst:
        dst.write(arr.astype(dtype), 1)


def _bloques(salida, max_lado):
    """Reduce por bloques conservando la presencia de cada clase (padding exacto)."""
    h, w = salida.shape
    b = max(1, int(math.ceil(max(h, w) / max_lado)))
    ph, pw = (-h) % b, (-w) % b
    s = np.pad(salida, ((0, ph), (0, pw)), constant_values=CLASE_NADA)
    hh, ww = s.shape
    return s.reshape(hh // b, b, ww // b, b).transpose(0, 2, 1, 3).reshape(hh // b, ww // b, b * b)


def guardar_vista_previa(ruta, salida, max_lado=1000):
    """azul = agua nueva | naranja = aumento | gris = sin datos | claro = nada"""
    blk = _bloques(salida, max_lado)
    img = np.empty(blk.shape[:2] + (3,), np.uint8)
    img[:] = (242, 242, 242)
    img[(blk == CLASE_NODATA).any(2)] = (150, 155, 160)
    img[(blk == CLASE_AUMENTO).any(2)] = (239, 108, 0)
    img[(blk == CLASE_AGUA).any(2)] = (21, 101, 192)
    cv.imwrite(ruta, img[:, :, ::-1])


def png_mascara_web(ruta, salida, max_lado=1600):
    """RGBA transparente: solo se pintan las clases 1 y 2 (para ImageOverlay)."""
    blk = _bloques(salida, max_lado)
    img = np.zeros(blk.shape[:2] + (4,), np.uint8)
    img[(blk == CLASE_AUMENTO).any(2)] = (239, 108, 0, 200)
    img[(blk == CLASE_AGUA).any(2)] = (21, 101, 192, 220)
    cv.imwrite(ruta, img[:, :, [2, 1, 0, 3]])


def png_diferencia_web(ruta, diferencia, valid, rango=8.0, ruido_db=1.0, max_lado=1600):
    """RGBA: azul = cae la senal, rojo = sube. Transparente si |cambio| < ruido_db."""
    h, w = diferencia.shape
    esc = min(1.0, max_lado / max(h, w))
    nh, nw = max(1, round(h * esc)), max(1, round(w * esc))
    d = cv.resize(np.where(valid, diferencia, 0).astype(np.float32), (nw, nh), interpolation=cv.INTER_AREA)
    v = cv.resize(valid.astype(np.float32), (nw, nh), interpolation=cv.INTER_AREA) > 0.5
    t = np.clip(d / rango, -1, 1)
    img = np.zeros((nh, nw, 4), np.uint8)
    neg = t < 0
    img[neg, 0:3] = (21, 101, 192)
    img[~neg, 0:3] = (200, 30, 30)
    img[..., 3] = (np.abs(t) * 200).astype(np.uint8)
    img[(~v) | (np.abs(d) < ruido_db), 3] = 0
    cv.imwrite(ruta, img[:, :, [2, 1, 0, 3]])


def construir_geojson(clases, resumen):
    """FeatureCollection con anillos cerrados; coordenadas [lon, lat] (estandar GeoJSON)."""
    feats = []
    for nombre, an in clases.items():
        if not an:
            continue
        for r in an["regiones"]:
            ring = r.get("poligono_lonlat")
            if not ring or len(ring) < 3:
                continue
            props = {k: v for k, v in r.items() if k not in ("poligono_lonlat", "centroide", "id")}
            props.update({"clase": nombre, "id": f"{nombre}-{r['id']}",
                          "centroide_lon": r["centroide"]["lon"], "centroide_lat": r["centroide"]["lat"]})
            feats.append({
                "type": "Feature",
                "id": props["id"],
                "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
                "properties": props,
            })
    return {"type": "FeatureCollection", "features": feats, "resumen": resumen}


# ==========================================================================
# PRINCIPAL
# ==========================================================================
def main():
    a = parse_args()
    os.makedirs(a.salida, exist_ok=True)
    ruta = lambda n: os.path.join(a.salida, n)

    print(f"FloodyLens: {a.antes} -> {a.despues}")
    try:
        antes, despues, meta = cargar_escenas(a.antes, a.despues)
    except rasterio.errors.RasterioIOError as e:
        sys.exit(f"Error abriendo una imagen: {e}")

    for nombre, m in (("antes", antes), ("despues", despues)):
        print(f"[{nombre}] min={np.nanmin(m):.4g} max={np.nanmax(m):.4g} "
              f"media={np.nanmean(m):.4g} nan={np.isnan(m).mean() * 100:.1f}%")

    # 1. Escala comun en dB (sin normalizar cada imagen por separado)
    antes_db, lin_a = normalizar_a_db(antes)
    despues_db, lin_d = normalizar_a_db(despues)
    if lin_a or lin_d:
        print("Datos lineales detectados -> convertidos a dB.")
    valid = np.isfinite(antes_db) & np.isfinite(despues_db)
    if not valid.any():
        sys.exit("No hay pixeles validos comunes en ambas imagenes.")

    # 2. Filtro de mediana contra el speckle (NaN rellenados con la mediana)
    ba = cv.medianBlur(np.where(valid, antes_db, np.nanmedian(antes_db)).astype(np.float32), a.mediana_ksize)
    da = cv.medianBlur(np.where(valid, despues_db, np.nanmedian(despues_db)).astype(np.float32), a.mediana_ksize)

    # 3. Algebra de mapas CON SIGNO
    diferencia = da - ba
    if a.normalizar_mediana:
        med = float(np.median(diferencia[valid]))
        diferencia = diferencia - med
        print(f"Diferencia normalizada: restados {med:+.2f} dB")
    dv = diferencia[valid]
    print(f"Diferencia (dB) -> min={dv.min():.2f} max={dv.max():.2f} "
          f"mediana={np.median(dv):.2f} media={dv.mean():.2f} std={dv.std():.2f}")

    # 4. Clases
    perm = cargar_agua_permanente(meta, a)
    clase1 = detectar_caida(diferencia, da, valid, perm, a)
    clase2 = detectar_aumento(diferencia, valid, perm, a)

    salida = np.zeros(clase1.shape, np.uint8)
    salida[clase2 == 1] = CLASE_AUMENTO
    salida[clase1 == 1] = CLASE_AGUA
    salida[~valid] = CLASE_NODATA
    tot = salida.size
    print("Recuento -> " + "  ".join(
        f"{n}: {int((salida == v).sum())} px ({(salida == v).sum() / tot * 100:.2f}%)"
        for v, n in ((0, "nada"), (1, "agua nueva"), (2, "aumento"), (255, "sin datos"))))

    # 5. Sensibilidad al umbral
    m2_px, _ = pixel_area(meta)
    sens = []
    if not a.sin_sensibilidad and a.sensibilidad:
        print("Sensibilidad al umbral:")
        sens = analisis_sensibilidad(diferencia, da, valid, perm, a, m2_px)

    # 6. Rasters y capas web
    guardar_tif(ruta("water_level.tif"), salida, meta, "uint8", CLASE_NODATA)
    guardar_tif(ruta("diferencia_db.tif"), np.where(valid, diferencia, np.nan), meta, "float32", float("nan"))
    guardar_vista_previa(ruta("vista_previa_mascara.png"), salida)
    png_mascara_web(ruta("mascara_web.png"), salida)
    png_diferencia_web(ruta("diferencia_web.png"), diferencia, valid)

    # 7. Descriptores, JSON y GeoJSON
    an1 = analizar_mascara(clase1, meta, a.top)
    an2 = analizar_mascara(clase2, meta, a.top)
    vacio = {"global": None, "regiones": []}

    lim = limites_wgs84(meta)
    crs = meta["crs"]
    if crs is None or not (crs.is_geographic and crs.to_epsg() == 4326):
        print("Aviso: la escena no esta en EPSG:4326; los PNG web asumen la malla original. "
              "Reproyecta a 4326 si vas a superponerlos en un mapa.")

    resultado = {
        "proyecto": "FloodyLens",
        "entrada": {
            "antes": a.antes, "despues": a.despues,
            "fecha_antes": a.fecha_antes or os.path.splitext(os.path.basename(a.antes))[0],
            "fecha_despues": a.fecha_despues or os.path.splitext(os.path.basename(a.despues))[0],
        },
        "parametros": {
            "umbral_cambio_db": a.umbral, "agua_max_db": a.agua_max,
            "umbral_aumento_db": a.umbral_aumento, "normalizar_mediana": a.normalizar_mediana,
            "median_ksize": a.mediana_ksize, "kernel_morfo": a.kernel,
            "area_min_px": a.area_min, "area_min_aumento_px": a.area_min_aumento,
            "filtrar_mar": not a.sin_filtro_mar, "agua_permanente": a.agua_permanente,
        },
        "georreferencia": {
            "crs": str(crs), "ancho_px": meta["width"], "alto_px": meta["height"],
            "area_pixel_m2": m2_px, "limites_wgs84": lim,
        },
        "estadisticas": {
            "pixeles_validos": int(valid.sum()),
            "porcentaje_agua_nueva": round(float((salida == CLASE_AGUA).sum()) / max(int(valid.sum()), 1) * 100, 3),
            "diferencia_mediana_db": float(np.median(dv)),
            "diferencia_std_db": float(dv.std()),
        },
        "archivos": {
            "mascara_tif": "water_level.tif", "diferencia_tif": "diferencia_db.tif",
            "geojson": "resultados.geojson", "mascara_png": "mascara_web.png",
            "diferencia_png": "diferencia_web.png",
        },
        "sensibilidad_umbral": sens,
        **(an1 or vacio),                                   # clase 1 en la raiz
        "posible_inundacion_aumento": an2 or vacio,         # clase 2: menor confianza
    }
    with open(ruta("results.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)

    resumen = {"fecha_antes": resultado["entrada"]["fecha_antes"],
               "fecha_despues": resultado["entrada"]["fecha_despues"],
               "area_agua_nueva_ha": an1["global"]["area_ha"] if an1 else 0.0,
               "limites_wgs84": lim}
    with open(ruta("resultados.geojson"), "w", encoding="utf-8") as f:
        json.dump(construir_geojson({"agua_nueva": an1, "aumento": an2}, resumen),
                  f, ensure_ascii=False)

    print(f"Salidas escritas en: {os.path.abspath(a.salida)}")
    if an1:
        g = an1["global"]
        print(f"Agua nueva: {g['area_ha']} ha en {g['num_manchas']} manchas")
    else:
        print("Clase 1 vacia: revisa diferencia_db.tif y ajusta --umbral / --agua-max.")
    if an2:
        g = an2["global"]
        print(f"Aumento (posible inundacion urbana/vegetacion): {g['area_ha']} ha en {g['num_manchas']} manchas")


if __name__ == "__main__":
    main()