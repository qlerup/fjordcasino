# FjordCasino logo and icon package

The same visual family as FjordHub, FjordBudget and FjordLens: a rounded deep-green tile with polished edges, golden chips, playing cards and a duck embossed on the front chip.

`icon-master.png` is the original generated with imagegen using the three apps as style references. Exports preserve the complete illustration and transparency. SVG files embed the raster original rather than being hand-drawn vector originals.

`exports.json` lists all 27 deliverables: PNG icons from 16 to 1024 px, ICO, ICNS, Apple touch icon, maskable icons, SVG mark, horizontal/stacked logos with light/dark text, and 1200 × 630 social cards. `light` means light text for dark backgrounds; `dark` means dark text for light backgrounds.

Rebuild with `python scripts/build_brand.py` using Pillow and Playwright Chromium. Colors: deep green `#143c35`, champagne gold `#c7ad74`, light text `#edf3f7`. Wordmarks use Arial Bold, matching the suite's export pipeline. Leave clear space at least one tenth of the icon width. Use maskable exports where a platform crops the icon.
