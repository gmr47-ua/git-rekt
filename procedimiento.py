"""Detección exploratoria de posible inundación en toda la escena SAR VV."""
from pathlib import Path
import argparse
import json
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy import ndimage
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from rasterio.warp import transform as transformar

def leer_sigma_lineal(ruta):
    """Leer sigma0 lineal y excluir valores inválidos."""

    if not ruta.is_file():
        raise FileNotFoundError(
            f"No se encuentra el archivo:\n{ruta}"
        )

    with rasterio.open(ruta) as src:
        if src.count != 1:
            raise ValueError(
                f"{ruta.name}: se esperaba una sola banda."
            )

        if src.crs is None:
            raise ValueError(
                f"{ruta.name}: falta el sistema de coordenadas."
            )

        imagen = src.read(1).astype("float32")
        mascara = src.read_masks(1) > 0
        perfil = src.profile.copy()

    validos = (
        mascara
        & np.isfinite(imagen)
        & (imagen > 0)
    )

    imagen[~validos] = np.nan

    return imagen, perfil


# ============================================================
# ALINEACIÓN
# ============================================================

def alinear_con_referencia(origen, perfil_origen, perfil_ref):
    """Alinear la imagen posterior sobre la cuadrícula anterior."""

    forma = (
        perfil_ref["height"],
        perfil_ref["width"],
    )

    misma_cuadricula = (
        origen.shape == forma
        and perfil_origen["crs"] == perfil_ref["crs"]
        and perfil_origen["transform"] == perfil_ref["transform"]
    )

    if misma_cuadricula:
        print("Las imágenes ya comparten cuadrícula.")
        return origen.copy()

    print("Alineando el 31 de octubre sobre el 19 de octubre...")

    alineada = np.full(
        forma,
        np.nan,
        dtype="float32",
    )

    # Interpolar sigma0 en escala lineal.
    reproject(
        source=origen,
        destination=alineada,
        src_transform=perfil_origen["transform"],
        src_crs=perfil_origen["crs"],
        src_nodata=np.nan,
        dst_transform=perfil_ref["transform"],
        dst_crs=perfil_ref["crs"],
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
        init_dest_nodata=True,
    )

    # Alinear también la máscara de validez.
    validez_origen = (
        np.isfinite(origen)
        & (origen > 0)
    ).astype("uint8")

    validez_destino = np.zeros(
        forma,
        dtype="uint8",
    )

    reproject(
        source=validez_origen,
        destination=validez_destino,
        src_transform=perfil_origen["transform"],
        src_crs=perfil_origen["crs"],
        dst_transform=perfil_ref["transform"],
        dst_crs=perfil_ref["crs"],
        dst_nodata=0,
        resampling=Resampling.nearest,
        init_dest_nodata=True,
    )

    validos = (
        (validez_destino == 1)
        & np.isfinite(alineada)
        & (alineada > 0)
    )

    alineada[~validos] = np.nan

    return alineada


def suavizar(a, tam):
    """Media local en potencia lineal, sin contaminar con NoData."""
    v = np.isfinite(a)
    peso = ndimage.uniform_filter(v.astype('float32'), size=tam, mode='constant')
    suma = ndimage.uniform_filter(np.where(v, a, 0), size=tam, mode='constant')
    return np.divide(suma, peso, out=np.full_like(a, np.nan), where=peso > 0)


def limpiar(m, minimo):
    etiquetas, _ = ndimage.label(m, structure=np.ones((3, 3)))
    tamanos = np.bincount(etiquetas.ravel())
    conservar = tamanos >= minimo
    conservar[0] = False
    return conservar[etiquetas]


def guardar(ruta, a, perfil, nodata):
    p = dict(driver='GTiff', width=a.shape[1], height=a.shape[0], count=1,
             dtype=a.dtype, crs=perfil['crs'], transform=perfil['transform'],
             nodata=nodata, compress='deflate')
    with rasterio.open(ruta, 'w', **p) as dst:
        dst.write(a, 1)


def detectar(b, a, validos, agua=-17, caida=-3, minimo=25):
    cambio = a-b
    previos = validos & (b < agua)
    candidatos = validos & ~previos & (a < agua) & (cambio <= caida)
    inundacion = limpiar(candidatos, minimo)
    # Disminución intensa sin oscuridad suficiente: evidencia separada, no inundación.
    ambiguos = limpiar(validos & ~previos & ~inundacion & (a >= agua) & (cambio <= -7), minimo)
    clases = np.full(a.shape, 255, dtype='uint8')
    clases[validos] = 0
    clases[previos] = 1
    clases[inundacion] = 2
    clases[ambiguos] = 3
    return inundacion, clases, cambio


def main():
    base = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--antes', type=Path, default=base/'19_octubre(1)(1).tif')
    p.add_argument('--despues', type=Path, default=base/'31_octubre(2)(1).tif')
    p.add_argument('--salida', type=Path, default=base/'resultados')
    p.add_argument('--agua-db', type=float, default=-17)
    p.add_argument('--caida-db', type=float, default=-3)
    p.add_argument('--filtro', type=int, default=3)
    p.add_argument('--min-pixeles', type=int, default=25)
    p.add_argument('--sin-ventana', action='store_true')
    args = p.parse_args()
    if args.filtro < 1 or args.filtro % 2 == 0 or args.min_pixeles < 1 or args.caida_db >= 0:
        p.error('Filtro impar positivo, mínimo >=1 y caída negativa requeridos.')
    args.salida.mkdir(parents=True, exist_ok=True)
    antes, perfil = leer_sigma_lineal(args.antes)
    despues, perfil_d = leer_sigma_lineal(args.despues)
    despues = alinear_con_referencia(despues, perfil_d, perfil)
    validos = np.isfinite(antes) & np.isfinite(despues)
    if not validos.any():
        raise ValueError('No hay cobertura válida común entre las imágenes.')
    b = 10*np.log10(suavizar(antes, args.filtro))
    a = 10*np.log10(suavizar(despues, args.filtro))
    b[~validos] = np.nan
    a[~validos] = np.nan
    inundacion, clases, cambio = detectar(b, a, validos, args.agua_db, args.caida_db, args.min_pixeles)
    mascara = np.where(validos, inundacion.astype('uint8'), 255).astype('uint8')
    guardar(args.salida/'mascara_inundacion.tif', mascara, perfil, 255)
    guardar(args.salida/'clasificacion.tif', clases, perfil, 255)
    guardar(args.salida/'cambio_db.tif', cambio.astype('float32'), perfil, np.nan)
    guardar(args.salida/'antes_filtrado_db.tif', b.astype('float32'), perfil, np.nan)
    guardar(args.salida/'despues_filtrado_db.tif', a.astype('float32'), perfil, np.nan)
    informe = dict(antes=str(args.antes), despues=str(args.despues),
                   agua_db=args.agua_db, caida_db=args.caida_db,
                   filtro=args.filtro, min_pixeles=args.min_pixeles,
                   pixeles_validos=int(validos.sum()), pixeles_candidatos=int(inundacion.sum()),
                   porcentaje_candidato=float(100*inundacion.sum()/validos.sum()),
                   limites=list(rasterio.transform.array_bounds(b.shape[0], b.shape[1], perfil['transform'])),
                   crs=str(perfil['crs']),
                   advertencia='Posible agua nueva; no es extensión validada ni máxima de la DANA. Agua previa significa superficie oscura en la fecha inicial, no agua permanente confirmada.')
    (args.salida/'estadisticas.json').write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding='utf-8')
    gris = plt.get_cmap('gray').copy()
    gris.set_bad('#dddddd')
    fig, ejes = plt.subplots(2, 2, figsize=(13, 12), sharex=True, sharey=True)
    fig.subplots_adjust(bottom=.16, top=.91, hspace=.22, wspace=.20)
    fig.suptitle('Valencia · toda la escena SAR\n19 → 31 octubre 2024 · detección de posible inundación', fontsize=15)
    for ax, datos, titulo, cmap, low, high in [
        (ejes[0,0], b, 'Antes · sigma⁰ VV filtrado', gris, -25, 0),
        (ejes[0,1], a, 'Después · sigma⁰ VV alineado y filtrado', gris, -25, 0),
        (ejes[1,0], cambio, 'Cambio: después − antes', 'RdBu_r', -10, 10)]:
        im = ax.imshow(datos, cmap=cmap, vmin=low, vmax=high, interpolation='nearest')
        ax.set_title(titulo)
        fig.colorbar(im, ax=ax, shrink=.75, label='dB')
    ax = ejes[1,1]
    ax.imshow(a, cmap=gris, vmin=-25, vmax=0)
    ax.imshow(np.ma.masked_where(~inundacion, np.ones_like(clases)), cmap=ListedColormap(['#00cfff']), vmin=0, vmax=1, alpha=.85, interpolation='nearest')
    ax.set_title('Resultado · posible inundación en cian')
    ax.legend(handles=[Patch(color='#00cfff', label='Posible agua nueva')], loc='upper right', fontsize=8)
    for ax in ejes.ravel():
        ax.set_xlabel('Columna de la escena')
        ax.set_ylabel('Fila de la escena')
    texto = fig.text(.06, .035, f'Después < {args.agua_db:g} dB | caída ≥ {abs(args.caida_db):g} dB | antes ≥ {args.agua_db:g} dB\nFiltro {args.filtro}×{args.filtro}; grupos ≥ {args.min_pixeles} píxeles. Clic para consultar. S para guardar.', fontsize=9)
    marcadores = [ax.plot([], [], '+', color='yellow', ms=12)[0] for ax in ejes.ravel()]
    def clic(event):
        if event.inaxes not in ejes.ravel() or event.xdata is None or event.ydata is None:
            return
        toolbar = getattr(fig.canvas.manager, 'toolbar', None)
        if toolbar and toolbar.mode:
            return
        c, f = int(round(event.xdata)), int(round(event.ydata))
        if not (0 <= f < a.shape[0] and 0 <= c < a.shape[1]):
            return
        for m in marcadores:
            m.set_data([c], [f])
        x, y = rasterio.transform.xy(perfil['transform'], f, c)
        lons, lats = transformar(perfil['crs'], 'EPSG:4326', [x], [y])
        lon, lat = lons[0], lats[0]
        estado = {0:'Sin detección', 1:'Oscuro antes: agua previa posible', 2:'Posible inundación', 3:'Caída intensa ambigua', 255:'Sin datos'}[int(clases[f,c])]
        texto.set_text(f'Fila {f}, columna {c} | lon {lon:.6f}, lat {lat:.6f}\nAntes {b[f,c]:.2f} dB | después {a[f,c]:.2f} dB | cambio {cambio[f,c]:.2f} dB | {estado}')
        fig.canvas.draw_idle()
    fig.canvas.mpl_connect('button_press_event', clic)
    ruta = args.salida/'resumen_inundacion.png'
    fig.canvas.mpl_connect('key_press_event', lambda e: fig.savefig(ruta, dpi=150) if e.key and e.key.lower()=='s' else None)
    fig.savefig(ruta, dpi=150)
    # Máscara PNG legible sin programa SIG.
    plt.imsave(args.salida/'mascara_inundacion.png', np.where(validos, inundacion, np.nan), cmap='gray', vmin=0, vmax=1)
    print(json.dumps(informe, indent=2, ensure_ascii=False))
    if not args.sin_ventana:
        plt.show()
    plt.close(fig)


if __name__ == '__main__':
    main()
