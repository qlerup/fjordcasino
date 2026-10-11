# FjordCasino logo- og ikonpakke

Samme visuelle familie som FjordHub, FjordBudget og FjordLens: afrundet, dyb grøn appflise med blanke kanter, gyldne jetoner, spillekort og en and præget i den forreste jeton.

`icon-master.png` er originalen genereret med imagegen med de tre apps som stilreferencer. Den komplette illustration og dens gennemsigtighed bevares i eksporterne. SVG-filerne indlejrer rasteroriginalen; de er ikke håndtegnede vektororiginaler.

`exports.json` indeholder alle 27 leverancer: PNG-ikoner fra 16 til 1024 px, ICO, ICNS, Apple-touch-ikon, maskable ikoner, SVG-mark, vandrette og stablede logoer med lys/mørk tekst samt socialkort på 1200 × 630 px. `light` betyder lys tekst til mørk baggrund; `dark` er mørk tekst til lys baggrund.

Genbyg med `python scripts/build_brand.py` (Pillow og Playwright Chromium). Farver: dyb grøn `#143c35`, champagneguld `#c7ad74`, lys tekst `#edf3f7`. Skrift til logoerne: Arial Bold, som i de andre apps' eksportpipeline. Hold frirum omkring logoet på mindst en tiendedel af ikonets bredde. Brug maskable-filerne, når en platform selv beskærer ikonet.
