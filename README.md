# FloodyLens — SAR flood-change viewer (NISAR + Sentinel-1)

Built by team **git-rekt** for the NASA Space Apps Challenge 2026
(*"Earth's surface in motion: tracking change with NISAR radar"*).

<img width="1600" height="533" alt="FloodyLensLogo" src="https://github.com/user-attachments/assets/f290590d-9850-481f-8a83-c02d43340f10" />

---

# **git-rekt team:** 
- Unai López González, 
- Javier López Castellanos, 
- Gabriel Morcillo Rubio,
- Pedro Femenía Córdoba,
- Marius Antonio Nica.

**Oficial Website:** https://floodylens-web.slc5o2.easypanel.host

---

# **About the project:**

FloodyLens takes **two radar (SAR) images of the same place, before and after an event**, finds the areas
that became dark (calm water reflects the radar signal away from the satellite), and presents the result in
an interactive web app:

- a **swipe slider** to compare "before" and "after" images, with the **date and the satellite** printed on each
- an **interactive map** with the coverage of each sensor and the detected water layers (Sentinel-1 in blue, NISAR in orange)
- a separate **NISAR (L-band) before/after comparison**
- **metrics** (area, number of patches, shape descriptors) and an optional **population exposure** estimate (WorldPop)
- an optional **AI-written summary** of the numbers

> ⚠️ **This is an exploratory tool.** The output is a *candidate* "new water" mask. It is **not** a validated
> flood map and it is not an official affected area.

---

## 1. How it works

```
before.tif + after.tif ──► procedimiento.py ──► resultados/ ──► exportar_app.py ──► data/<case>/ ──► app.py
 (Sentinel-1, linear)       detect new water      masks, PNGs     convert + metrics        ▲
                                                                                          │
                                           poblacion.py  (optional: WorldPop population) ─┤
                          exportar_nisar.py  (optional: NISAR images + NISAR water mask) ─┘
```

Detection rule (in `procedimiento.py`), applied pixel by pixel after a 3×3 mean filter in linear power:

> **new water** = darker than `--agua-db` in the *after* image **and** not that dark in the *before* image
> **and** the signal dropped by at least `|--caida-db|` dB; patches smaller than `--min-pixeles` are removed.

Defaults: `-17 dB`, `-3 dB`, filter `3`, minimum `25` pixels. These values were chosen for the Valencia case
and **have not been validated for other regions** — you may need to tune them (see step 3).

---

## 2. Installation

**Python:** developed on Python 3.14 / Windows. Other versions and operating systems are untested
(`rasterio` needs a pre-built wheel for your Python version).

```bash
git clone <this repository>
cd git-rekt

python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
```

> On Windows the launcher `py` works in place of `python` (e.g. `py procedimiento.py ...`).
> On macOS/Linux use `python3` if `python` is not available.
> **Always run the commands from the repository root:** the app reads the `data/` folder relative to where you start it.

The app uses recent Streamlit options (e.g. `width="stretch"`). If you see an error about an unexpected
`width` argument, upgrade with `pip install -U streamlit`.

---

## 3. Quick test (no real data needed)

This checks that your installation works, using a **synthetic** example (not real data):

```bash
python crear_demo.py
python -m streamlit run app.py
```

The browser opens at <http://localhost:8501>. Choose **Demo** in the left sidebar.

---

## 4. Run it with your own region

Example: a flood in another part of the world. Use `my_region` as a placeholder for any folder name.

### Step 1 — Prepare two SAR images

| Requirement | Why |
|---|---|
| **Two GeoTIFFs** of the same area (they must overlap) | before and after the event |
| **One band only** (one polarization, e.g. VV or HH) | the scripts stop if there is more than one band |
| **Linear backscatter** (σ⁰ or γ⁰ in *power*, values > 0) — **not dB** | the detector filters in linear power and converts to dB itself |
| **A coordinate system (CRS) defined** | any CRS works; the second image is reprojected onto the first one's grid |
| Same sensor, polarization and (ideally) orbit direction for both dates | different geometries create false changes |

The Valencia example images are roughly 2,200–2,800 px per side. Much larger scenes will need more memory and time
(not tested).

**Check your files** before running anything:

```python
import rasterio, numpy as np

with rasterio.open("before.tif") as s:
    a = s.read(1)
    v = a[np.isfinite(a)]
    print("bands:", s.count, "| CRS:", s.crs, "| pixel size:", s.res, "| dtype:", s.dtypes[0])
    print("min/max:", v.min(), v.max(), "| share of values > 0:", round(float((v > 0).mean()), 3))
```

If the share of values above 0 is low (most values negative, e.g. −25 … 0), your data is in **dB**. Convert it:

```python
import rasterio, numpy as np

with rasterio.open("before_db.tif") as s:
    profile, db = s.profile, s.read(1).astype("float32")
profile.update(dtype="float32", count=1)
with rasterio.open("before_linear.tif", "w", **profile) as dst:
    dst.write(10 ** (db / 10), 1)          # dB -> linear power
```

**Where to get data.** Any source works as long as the files meet the table above; no particular download tool is
required. Sentinel-1 (C-band) can be obtained, for example, from the Copernicus Data Space Ecosystem or from ASF.
For NISAR (L-band), use the resource list provided by the challenge and NASA's official NISAR data pages, since
access and product names may change.

### Step 2 — Detect candidate new water

```bash
python procedimiento.py --antes before.tif --despues after.tif --salida resultados --sin-ventana
```

- `--antes` = before image, `--despues` = after image. **Always pass them**: the defaults point to the Valencia files.
- Optional tuning: `--agua-db -17`, `--caida-db -3`, `--filtro 3` (odd number), `--min-pixeles 25`.
- `--sin-ventana` skips the interactive matplotlib window (it still saves the summary figure).
- If a file name contains parentheses or spaces, **put it in quotes**.

Main outputs in `resultados/`:

| File | Content |
|---|---|
| `mascara_inundacion.tif` | candidate water mask (1 = candidate, 0 = none, 255 = no data) |
| `clasificacion.tif` | 0 none · 1 already dark before · 2 candidate · 3 strong drop, not dark enough · 255 no data |
| `cambio_db.tif`, `antes_filtrado_db.tif`, `despues_filtrado_db.tif` | change and filtered images in dB |
| `estadisticas.json` | parameters and pixel counts |
| `resumen_inundacion.png` | 4-panel summary figure |

### Step 3 — Export for the app

```bash
python exportar_app.py resultados data/my_region --nombre "Possible flooding in <place>" --descripcion "Short description of the event and the data" --sensor "Sentinel-1 (banda C)" --polarizacion VV --fecha-antes 2025-01-10 --fecha-despues 2025-01-22
```

**You must override `--nombre`, `--fecha-antes` and `--fecha-despues`**, otherwise the app shows the Valencia
defaults (2024-10-19 → 2024-10-31). Dates use the format `YYYY-MM-DD`.

This creates `data/my_region/` with `mascara_agua.tif`, `results.json`, `antes.png`, `despues.png` and `resumen.png`.
The folder name becomes the case name in the app's sidebar (`my_region` → "My Region"). You can create several
folders under `data/` and switch between them.

Metrics are computed on a metric grid: if your CRS is geographic (degrees), the mask is reprojected to a UTM zone
chosen automatically from the area's centre, at 10 m.

> **Before presenting results for a new region**, open `exportar_app.py` and edit the `LIMITACIONES` list at the top:
> its default sentences mention the Albufera, the DANA storm and Paiporta (Valencia). The same Valencia wording
> appears in the title of the figure in `procedimiento.py` (`fig.suptitle`) and in the `advertencia` text of
> `estadisticas.json`.

### Step 4 (optional) — Population exposure

```bash
python poblacion.py data/my_region --iso3 XXX
```

Replace `XXX` with the **3-letter ISO country code** (e.g. `ESP`, `BGD`, `USA`). Without `--iso3` the script tries
to detect the country through OpenStreetMap (Nominatim).

- It reads only the needed window of the **WorldPop 2020** population raster (needs an internet connection) and
  falls back to downloading the whole country file into `cache_worldpop/`.
- If the automatic download fails, download the country raster manually from the WorldPop *Global 2000–2020* listing
  (<https://hub.worldpop.org/geodata/listing?id=29>) and pass it as a second argument:
  `python poblacion.py data/my_region path/to/population.tif`
- The result is written to `results.json` and the app then shows **"Población Afectada"**.
- If you regenerate the mask later, **run this step again**, otherwise the population refers to the old mask.

It is an **estimate of the population living in the candidate areas** (modelled 2020 data, assuming people are spread
evenly inside each cell). It is not a count of people actually affected.

### Step 5 — Add NISAR images and water layer

```bash
python procedimiento.py --antes nisar_before.tif --despues nisar_after.tif --salida resultadosNISAR --sin-ventana

python exportar_nisar.py nisar_before.tif nisar_after.tif data/my_region
```

- Both NISAR files must have **exactly the same grid** (same size, CRS and transform). If they do not, resample the
  second one onto the first before running (e.g. with `gdalwarp` or `rasterio.warp.reproject`).
- Dates are read from the file names (an 8-digit `YYYYMMDD` block, e.g. `..._20261004_...`). If the names have no
  date, add `--fecha-antes YYYY-MM-DD --fecha-despues YYYY-MM-DD`.
- It accepts the same tuning flags as step 2: `--agua-db`, `--caida-db`, `--filtro`, `--min-pixeles`.
- It creates `nisar_antes.png`, `nisar_despues.png`, `nisar.json` and `nisar_mascara_agua.tif` inside `data/my_region/`.
- The labels "NISAR (banda L)" and polarization "HH" are written as fixed text in `exportar_nisar.py` (`meta`).
  Edit them if you use another polarization.
- The NISAR dates can differ from the main (Sentinel-1) pair. The app then shows a warning: different sensors and
  dates are **not directly comparable**, and the area, population and AI report come only from the main pair.

### Step 6 — Launch the app

```bash
python -m streamlit run app.py
```

In the sidebar you can choose the case and one of three views:

| View | What you see |
|---|---|
| **Comparación directa (antes/después)** | swipe slider, main pair (Sentinel-1), with sensor label and dates |
| **Comparación NISAR (banda L)** | swipe slider with the NISAR pair (orange label), plus a warning about comparability |
| **Superposición de radar (Capa de agua)** | map with the coverage of each sensor, the water layers (**blue = Sentinel-1, orange = NISAR**), a layer control and an opacity slider |

Below, the app shows download buttons (PNG with the water overlay, mask GeoTIFF, results JSON), the metrics, the
limitations and the AI summary. The map background tiles need an internet connection.

Cards show **N/D** when a value is missing: "Población Afectada" appears only after step 4, and "Fiabilidad de
Detección SAR" only if `results.json` contains a `fiabilidad` value (it is **not** computed automatically).

---

## 5. Optional: AI-written summary

The "Actualizar Informe de IA" button sends the numbers in `results.json` to a language model through an
OpenAI-compatible API (ModelScope by default, see `qwen.py`).

Create a file named `.env` in the repository root:

```
MODELSCOPE_API_KEY=your_key_here
# optional overrides (defaults are defined in qwen.py)
# MODELSCOPE_BASE_URL=...
# MODELSCOPE_MODEL=...
```

Without a key, the app keeps working and shows a short local text instead. The model's prompt asks for an alert
level and recommended actions; since the detection is unvalidated, **treat the generated text as illustrative and
review it before using it**.

---

## 6. Project layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit web app |
| `procedimiento.py` | change detection on the before/after pair |
| `exportar_app.py` | converts `resultados/` into the `data/<case>/` folder (metrics, PNGs) |
| `exportar_nisar.py` | NISAR images, footprint and NISAR water mask for the app |
| `poblacion.py` | WorldPop population exposure |
| `qwen.py` | AI report client (used by `app.py`) |
| `crear_demo.py` | synthetic test case |

What the app expects inside `data/<case>/`:

| File | Required | Content |
|---|---|---|
| `results.json` | recommended | name, sensor, dates, metrics, limitations |
| `mascara_agua.tif` | for the map | 0/1 water mask with a CRS |
| `antes.png`, `despues.png` | for the slider | before/after images |
| `resumen.png` | no | summary figure |
| `nisar_antes.png`, `nisar_despues.png`, `nisar.json` | no | NISAR comparison view |
| `nisar_mascara_agua.tif` | no | NISAR water layer on the map |
| `poblacion.tif` | no | WorldPop window (created by `poblacion.py`) |

---

## 7. Known limitations

- **Exploratory, not validated.** Thresholds were chosen for Valencia. Compare any result with an independent source
  (official flood maps, optical imagery, field reports) before drawing conclusions.
- **Radar-specific false positives:** radar shadow in mountainous terrain, wet or smooth bare soil, and
  agricultural changes (for example flooded rice paddies) can look like new water. There is no terrain or shadow mask.
- **Missed floods:** water under vegetation or inside cities often looks *brighter*, not darker, and wind-roughened
  water does not look dark. These floods are not detected by this rule.
- **Metrics are aggregates:** area, perimeter, compactness and Hu moments describe *all* candidate patches together,
  so for a fragmented mask the shape descriptors are not meaningful.
- **Two sensors, two bands:** Sentinel-1 is C-band and NISAR is L-band. Their dB values are not directly comparable,
  and the default thresholds were not calibrated for L-band.
- **Hard-coded Valencia / Sentinel wording:** the map legend labels the main layer as "Sentinel-1 (banda C)", and the
  defaults mentioned in steps 3 and 5 refer to Valencia. If your main sensor is different, edit those strings in
  `app.py` and `exportar_app.py`.

---

## 8. Troubleshooting

| Message or symptom | Likely cause and fix |
|---|---|
| `ModuleNotFoundError` | run `pip install -r requirements.txt` inside your virtual environment |
| `No se encuentra el archivo` | wrong path; check the working directory and quote names with spaces or parentheses |
| `se esperaba una sola banda` | the GeoTIFF has several bands; extract one polarization into a single-band file |
| `falta el sistema de coordenadas` | the file has no CRS; assign one (e.g. in QGIS or with `gdal_edit.py -a_srs`) |
| `No hay cobertura válida común entre las imágenes` | the images do not overlap, or the data is in **dB** (non-positive values are discarded): convert to linear |
| `La mascara no contiene ningun pixel de agua` | no candidates found: check the pair and dates, or relax `--agua-db` / `--caida-db` (more candidates, but also more false positives) |
| `Las dos imagenes NISAR no comparten cuadricula` | resample the second NISAR image onto the first one's grid |
| `poblacion.py` fails to download | download the raster manually (step 4) and pass its path |
| App says "Sin datos todavia" | there is no `data/<case>/` folder, or you started Streamlit outside the repository root |
| Map has no background | the basemap tiles need internet |
| Error mentioning `width` | `pip install -U streamlit` |
| AI report shows a warning | missing or invalid `MODELSCOPE_API_KEY`; the app falls back to a local text |

---

## 9. Data architecture and SAR processing (current state)

The analytical core of the prototype is the extraction of **water masks from Synthetic Aperture Radar (SAR)
imagery**.

**Preprocessing with SNAP.** At present, the raw satellite data is preprocessed with ESA's **SNAP (Sentinel
Application Platform)**. We designed a geometric and radiometric workflow (Graph Builder) that applies
**thermal noise removal**, **calibration to backscatter** (σ⁰, VV polarization for the Sentinel-1 pair) and
**Range-Doppler Terrain Correction** using Digital Elevation Models. This workflow is meant to provide the spatial
accuracy needed to line up the detected water pixels with the streets of the affected municipalities. However, it
currently requires running the graphs **manually**.

**Where the manual/automatic line is today**

| Stage | Status |
|---|---|
| Downloading the SAR scenes and preprocessing them in SNAP | Manual |
| Change detection, metrics, export, population estimate, NISAR panel and web app | Scripted in Python (see section 4 for the commands and section 10 for the code), starting from calibrated, linear-backscatter GeoTIFFs |

**Next engineering milestone: a fully automated pipeline.** The goal is to replace SNAP's graphical interface with
scripted ingestion (for example, integrating the Copernicus / NASA Earthdata APIs and batch-processing libraries)
that downloads, filters and exports the GeoTIFF arrays without human intervention, so that the system can run
autonomously in response to any weather alert. This is closely related to the *"Real-time cloud processing
(bypassing SNAP)"* pillar of the roadmap shown at the bottom of the app.

---

## 10. Project structure and code modules

A short guide to what each file contains and does. The commands to run them are in section 4, and the files the
app expects inside `data/<case>/` are listed in section 6.

### Processing (offline, run once per event)

- **`procedimiento.py` — core SAR change detection.** Reads the before/after GeoTIFFs (single band, linear
  backscatter), discards invalid pixels and, if the grids differ, reprojects the *after* image onto the *before*
  grid. It smooths both with a 3×3 mean filter in linear power (ignoring no-data), converts to dB and applies the
  detection rule: darker than −17 dB *after*, not that dark *before*, and a drop of at least 3 dB; patches under
  25 pixels (8-connectivity) are removed. The thresholds are fixed values set from the command line (not adaptive),
  and the module relies on NumPy, SciPy and rasterio (it does not use OpenCV). It outputs the candidate mask
  (1 / 0 / 255 = no data), a four-class classification, change and filtered images in dB, `estadisticas.json` and a
  4-panel summary figure (matplotlib) in which you can click a pixel to read its values.
- **`exportar_app.py` — bridge to the app.** Takes the `resultados/` folder and builds `data/<case>/`: a clean 0/1
  water mask, `antes.png` / `despues.png` (grayscale, −25…0 dB), the summary figure and `results.json`. The metrics
  are computed on a metric grid (UTM, 10 m): area in hectares, perimeter (exposed pixel edges), compactness,
  elongation, the seven Hu moments (implemented in NumPy), centroid and number of patches. It keeps any keys that
  other scripts already wrote (e.g. the population) and holds the editable list of limitations.
- **`exportar_nisar.py` — NISAR preparation.** Takes two NISAR GeoTIFFs (HH, linear γ⁰) and writes
  `nisar_antes.png` and `nisar_despues.png` (−30…0 dB, 3×3 mean), `nisar.json` (sensor, dates parsed from the file
  names, WGS84 footprint polygon, detection statistics) and `nisar_mascara_agua.tif`, using the same detection
  logic as `procedimiento.py`. The two images must share exactly the same grid.
- **`poblacion.py` — population exposure.** Estimates the population exposed to the flood: it crosses the water
  mask with a WorldPop population raster (people per pixel) and can automatically download the raster for the area.
  The country is detected with OpenStreetMap Nominatim (plus an ISO3 code) unless `--iso3` is given. It reads only
  the needed window of the WorldPop 2020 raster over HTTP and, if that fails, falls back to a size-checked full
  download cached in `cache_worldpop/`. It then reprojects the mask onto the population grid and sums
  *population × flooded fraction* per cell. The result goes into `results.json` (`poblacion_afectada`,
  `poblacion_total_zona`, `porcentaje_poblacion_afectada`). It is a modelled estimate based on 2020 data, not a
  count of people actually affected.

### Interface and AI (what the user sees)

- **`app.py` — Streamlit dashboard and interactive demo.** Reads the files in `data/<case>/` and does no heavy radar
  processing (only a light, cached reprojection of the masks for the map), which keeps the page fast. It provides:
  - a case selector and three views: Sentinel-1 swipe slider, NISAR swipe slider (with a comparability warning),
    and a Folium map with OpenStreetMap and Esri satellite base layers, the Sentinel-1 water layer in blue, the
    NISAR layer in orange, the coverage polygon of each sensor, a layer control and an opacity slider;
  - expanders with the summary figures, download buttons (PNG with the water overlay, mask GeoTIFF, results JSON)
    and metric cards that fall back to computed values when population or reliability are missing;
  - the limitations, the AI report, the future roadmap and the demo disclosure;
  - an **English / Spanish toggle** in the header: interface texts live in the `TEXTOS` dictionary, and texts that
    come from `results.json` are translated through `<field>_en` keys or a translation table.
- **`qwen.py` — AI report client.** Sends the case's *metrics* (the JSON, not the raster) to a language model through
  an OpenAI-compatible API (ModelScope by default; the key and model are read from `.env`). Its system prompts, in
  Spanish and English, ask for a four-part situation report: alert level, key data, affected areas and
  recommendations. The answer is streamed into the app. If the key is missing or the call fails, `informe_local()`
  returns a short offline text. Since the detection is unvalidated, treat the generated report as illustrative.
- **Frontend components (inside `app.py`).** There is no separate assets folder or CSS file: the swipe slider
  (HTML, CSS and JavaScript) and the sensor-coloured chips are HTML embedded in the Streamlit app. The images they
  display are generated files in `data/<case>/`.

### Support files and folders

- **`crear_demo.py`** — generates a *synthetic* test case in `data/demo/` (an elliptical water patch, fake
  before/after images and a GeoTIFF mask in UTM 30N near Valencia) to check that the installation works. It is not
  real data; delete `data/demo/` before presenting.
- **`requirements.txt`** — Python dependencies. `.env` (not committed) holds `MODELSCOPE_API_KEY`.
- **`data/<case>/`** — one folder per case study, read by the app.
- **`resultados/`, `resultadosNISAR/`, `cache_worldpop/`** — generated intermediate folders. The app reads the NISAR
  summary figure from `resultadosNISAR/resumen_inundacion.png` in the repository root.

---

## 11. Use of AI and third-party tools

**Development with AI assistance.** This application and the image-processing code have been developed with the
assistance of artificial intelligence. This covers `app.py`, `crear_demo.py`, `exportar_app.py`,
`exportar_nisar.py`, `poblacion.py`, `procedimiento.py` and `qwen.py`.

**Explanations and documentation.** The explanations that accompany the project have also been generated with the
help of artificial intelligence: this README, the docstrings and comments in the code, and the explanatory texts
shown in the app.

**AI report inside the app.** The situation report produced by the *"Update AI report"* button is written at run
time by a language model (see section 5). It is illustrative and has not been validated.

**SNAP.** The download and processing of the SAR images have been carried out using **SNAP (Sentinel Application
Platform)**, a tool provided by the European Space Agency (ESA), used for satellite image preprocessing and analysis
(see section 9).

---

## 12. Data credits

- Sentinel-1: contains modified Copernicus Sentinel data (ESA / European Commission).
- NISAR: NASA–ISRO SAR mission data.
- Population: WorldPop (University of Southampton).
- Basemaps: OpenStreetMap contributors; Esri World Imagery.

