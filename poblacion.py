"""
poblacion.py - Estima la poblacion expuesta a la inundacion.

Cruza la mascara de agua con un raster de poblacion de WorldPop
(personas por pixel). Puede DESCARGAR AUTOMATICAMENTE el raster de la zona.

Uso (automatico, recomendado):
    python poblacion.py data/paiporta
Uso con un raster que ya tengas:
    python poblacion.py data/paiporta ruta/poblacion.tif
Si falla la deteccion del pais:
    python poblacion.py data/paiporta --iso3 ESP

Desde procesamiento.py:
    from poblacion import actualizar_json
    actualizar_json("data/paiporta")

Dependencias extra: requests y pycountry (pip install requests pycountry)
"""
import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import WindowError
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

ANIO_MAX = 2020  # los datos individuales por pais de WorldPop llegan hasta 2020
BASES_URL = [
    "https://data.worldpop.org/GIS/Population/Global_2000_2020",
    "https://worldpop-public-data.soton.ac.uk/GIS/Population/Global_2000_2020",
]
CACHE_DIR = Path("cache_worldpop")
USER_AGENT = "FloodyLens-hackathon/1.0 (NASA Space Apps)"


# ----------------------------------------------------------------------
# 1) Que pais es?  (reverse geocoding con OpenStreetMap + codigo ISO3)
# ----------------------------------------------------------------------
def limites_wgs84(ruta_mascara):
    with rasterio.open(ruta_mascara) as m:
        return transform_bounds(m.crs, "EPSG:4326", *m.bounds)  # oeste, sur, este, norte


def iso3_desde_mascara(ruta_mascara):
    """Detecta el pais del centro de la mascara. Devuelve p.ej. 'ESP'."""
    import requests

    try:
        import pycountry
    except ImportError as e:
        raise RuntimeError("Falta pycountry: pip install pycountry (o usa --iso3 ESP)") from e

    o, s, e, n = limites_wgs84(ruta_mascara)
    lat, lon = (s + n) / 2, (o + e) / 2
    r = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 3},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    r.raise_for_status()
    iso2 = r.json().get("address", {}).get("country_code")
    if not iso2:
        raise RuntimeError("No se pudo detectar el pais; usa --iso3 (por ejemplo ESP).")
    return pycountry.countries.get(alpha_2=iso2.upper()).alpha_3


# ----------------------------------------------------------------------
# 2) Descargar SOLO la zona (sin bajar el pais entero)
# ----------------------------------------------------------------------
def recortar_a_zona(origen, limites, destino, margen=0.02):
    """
    Lee de 'origen' (URL o archivo) solo la ventana que cubre 'limites'
    (oeste, sur, este, norte en EPSG:4326) y la guarda en 'destino'.
    Con una URL, GDAL pide solo los bytes necesarios (HTTP range requests).
    """
    ruta = origen if not str(origen).startswith("http") else f"/vsicurl/{origen}"
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"
    ):
        with rasterio.open(ruta) as src:
            o, s, e, n = transform_bounds("EPSG:4326", src.crs, *limites)
            m = margen
            try:
                ventana = (
                    from_bounds(o - m, s - m, e + m, n + m, transform=src.transform)
                    .round_offsets()
                    .round_lengths()
                    .intersection(Window(0, 0, src.width, src.height))
                )
            except WindowError as err:
                raise ValueError("El raster no cubre la zona de la mascara.") from err
            datos = src.read(1, window=ventana)
            perfil = src.profile.copy()
            perfil.update(
                height=int(ventana.height),
                width=int(ventana.width),
                transform=src.window_transform(ventana),
                compress="lzw",
                tiled=False,
            )
            perfil.pop("blockxsize", None)
            perfil.pop("blockysize", None)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(destino, "w", **perfil) as dst:
        dst.write(datos, 1)
    return destino


def _descargar_archivo(url, local):
    """Descarga a un .part, comprueba el tamano y solo entonces lo renombra."""
    import requests

    local = Path(local)
    parcial = local.with_name(local.name + ".part")
    with requests.get(url, stream=True, timeout=(15, 120), headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        esperado = int(r.headers.get("Content-Length", 0))
        comprimido = bool(r.headers.get("Content-Encoding"))
        leidos = 0
        with open(parcial, "wb") as f:
            for trozo in r.iter_content(1 << 20):
                f.write(trozo)
                leidos += len(trozo)
                print(f"\r  descargados {leidos / 1e6:.0f} MB", end="", flush=True)
    print()
    if esperado and not comprimido and leidos != esperado:
        parcial.unlink(missing_ok=True)
        raise IOError(f"descarga incompleta ({leidos} de {esperado} bytes)")
    parcial.replace(local)


def _describir(e):
    causa = f" <- {type(e.__cause__).__name__}: {e.__cause__}" if e.__cause__ else ""
    return f"{type(e).__name__}: {e}{causa}"


def descargar_poblacion(ruta_mascara, destino, iso3=None, anio=ANIO_MAX, origenes=None):
    """
    Obtiene el raster de poblacion recortado a la zona de la mascara.
    'origenes' permite pasar URLs o rutas propias (util para pruebas).
    """
    import requests

    limites = limites_wgs84(ruta_mascara)
    if origenes is None:
        iso3 = (iso3 or iso3_desde_mascara(ruta_mascara)).upper()
        anio = min(int(anio), ANIO_MAX)
        origenes = [f"{b}/{anio}/{iso3}/{iso3.lower()}_ppp_{anio}.tif" for b in BASES_URL]

    errores = []
    for url in origenes:
        # a) Intento rapido: leer solo la ventana por HTTP
        try:
            return recortar_a_zona(url, limites, destino)
        except Exception as e:  # noqa: BLE001
            errores.append(f"{url}: {_describir(e)}")
        # b) Respaldo: descargar el archivo completo (decenas de MB) y recortar
        if str(url).startswith("http"):
            CACHE_DIR.mkdir(exist_ok=True)
            local = CACHE_DIR / Path(url).name
            for intento in (1, 2):
                try:
                    if not local.exists():
                        print(f"Descargando {Path(url).name} (puede tardar un poco)...")
                        _descargar_archivo(url, local)
                    return recortar_a_zona(local, limites, destino)
                except rasterio.errors.RasterioIOError as e:
                    # archivo en cache corrupto o incompleto: borrar y reintentar una vez
                    errores.append(f"{url} (intento {intento}, archivo ilegible): {_describir(e)}")
                    local.unlink(missing_ok=True)
                except Exception as e:  # noqa: BLE001
                    errores.append(f"{url} (descarga completa): {_describir(e)}")
                    break
    raise RuntimeError(
        "No se pudo obtener el raster de poblacion automaticamente:\n  "
        + "\n  ".join(errores)
        + "\nDescargalo a mano en https://hub.worldpop.org/geodata/listing?id=29 "
        "y pasalo como segundo argumento."
    )


# ----------------------------------------------------------------------
# 3) Cruce mascara x poblacion
# ----------------------------------------------------------------------
def poblacion_expuesta(ruta_mascara, ruta_poblacion, fuente="WorldPop 2020 (estimación)"):
    """Devuelve poblacion_afectada, poblacion_total_zona, porcentaje y fuente."""
    with rasterio.open(ruta_mascara) as m, rasterio.open(ruta_poblacion) as p:
        if m.crs is None or p.crs is None:
            raise ValueError("La mascara y el raster de poblacion deben tener CRS definido.")

        limites_p = transform_bounds(m.crs, p.crs, *m.bounds)
        try:
            ventana = (
                from_bounds(*limites_p, transform=p.transform)
                .round_offsets()
                .round_lengths()
                .intersection(Window(0, 0, p.width, p.height))
            )
        except WindowError as err:
            raise ValueError(
                "El raster de poblacion no cubre la zona de la mascara "
                "(revisa que sea el pais/region correcta)."
            ) from err

        pob = p.read(1, window=ventana, masked=True).astype("float64").filled(0.0)
        pob[~np.isfinite(pob)] = 0.0
        pob[pob < 0] = 0.0
        transform_v = p.window_transform(ventana)

        agua = (m.read(1) == 1).astype("float32")  # 255 = sin dato
        fraccion = np.zeros(pob.shape, dtype="float32")
        reproject(
            source=agua,
            destination=fraccion,
            src_transform=m.transform,
            src_crs=m.crs,
            dst_transform=transform_v,
            dst_crs=p.crs,
            resampling=Resampling.average,
        )

    fraccion = np.clip(fraccion, 0, 1)
    afectada = float((pob * fraccion).sum())
    total = float(pob.sum())
    return {
        "poblacion_afectada": int(round(afectada)),
        "poblacion_total_zona": int(round(total)),
        "porcentaje_poblacion_afectada": round(100 * afectada / total, 2) if total > 0 else None,
        "delta_poblacion": fuente,
    }


def actualizar_json(carpeta, ruta_poblacion=None, iso3=None):
    """Calcula la poblacion expuesta y la escribe en data/<caso>/results.json."""
    carpeta = Path(carpeta)
    mascara = carpeta / "mascara_agua.tif"
    if ruta_poblacion is None:
        ruta_poblacion = carpeta / "poblacion.tif"
        if not ruta_poblacion.exists():
            print("Descargando poblacion de la zona (WorldPop)...")
            descargar_poblacion(mascara, ruta_poblacion, iso3=iso3)
    stats = poblacion_expuesta(mascara, ruta_poblacion)
    ruta_json = carpeta / "results.json"
    datos = json.loads(ruta_json.read_text(encoding="utf-8")) if ruta_json.exists() else {}
    datos.update(stats)
    ruta_json.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Poblacion expuesta a la inundacion")
    ap.add_argument("carpeta", help="carpeta del caso, p.ej. data/paiporta")
    ap.add_argument("raster", nargs="?", help="raster de poblacion propio (opcional)")
    ap.add_argument("--iso3", help="codigo de pais de 3 letras (p.ej. ESP) si falla la deteccion")
    a = ap.parse_args()
    print(actualizar_json(a.carpeta, a.raster, a.iso3))
