# ptcgp-images

Card and UI images for Pokémon TCG Pocket.

Image paths correspond directly to the path views in the companion data repository: [Vociferix/ptcgp-data](https://github.com/Vociferix/ptcgp-data). Every image in this repository has a matching row in one of those views, and the view values are the exact relative paths used here.

All images are PNG files.

---

## Directory layout

```
cards/
  {SET}/
    {NUM:03}.png          e.g. cards/A1/001.png

elements/
  icons/
    {element}.png         e.g. elements/icons/fire.png
  symbols/
    {element}.png         e.g. elements/symbols/grass.png

packs/
  art/
    {SET}/
      {subtitle}.png      e.g. packs/art/A1/charizard.png
  logos/
    {SET}/
      {subtitle}.png      e.g. packs/logos/A1/charizard.png

promo_sources/
  {source}.png            e.g. promo_sources/wonder_pick.png

rarities/
  icons/
    {group}/
      {count}.png         e.g. rarities/icons/diamond/1.png
  symbols/
    {group}/
      {count}.png         e.g. rarities/symbols/star/2.png

sets/
  icons/
    {SET}.png             e.g. sets/icons/A1.png
  logos/
    {SET}.png             e.g. sets/logos/B2a.png
```

---

## Path conventions

### Cards

`cards/{SET}/{NUM:03}.png`

`{SET}` is the set code (`A1`, `B2a`, `P-A`, …). `{NUM:03}` is the card's collector number zero-padded to three digits.

Example: card #227 from Genetic Apex → `cards/A1/227.png`

### Elements

`elements/icons/{element}.png` and `elements/symbols/{element}.png`

`{element}` is the lowercase element name: `grass`, `fire`, `water`, `lightning`, `fighting`, `psychic`, `darkness`, `metal`, `dragon`, `colorless`.

Icons are the circular energy symbols used on cards. Symbols are the standalone type symbols used in the UI.

### Packs

`packs/art/{SET}/{subtitle}.png` and `packs/logos/{SET}/{subtitle}.png`

`{subtitle}` is the pack subtitle in lowercase with spaces replaced by underscores.

Examples:
- `packs/art/A1/charizard.png`
- `packs/logos/B1/mega_blaziken.png`
- `packs/art/P-A/vol_1.png`

### Promo sources

`promo_sources/{source}.png`

`{source}` is the promo source code in lowercase with spaces replaced by underscores.

Examples: `wonder_pick.png`, `gold_shop.png`, `shop.png`, `mission.png`, `pack.png`

### Rarities

`rarities/icons/{group}/{count}.png` and `rarities/symbols/{group}/{count}.png`

`{group}` is the lowercase rarity group name (`diamond`, `star`, `shiny`, `crown`). `{count}` is the number of group symbols shown for that rarity tier.

Examples:
- Common (Diamond ◆×1) → `rarities/icons/diamond/1.png`
- Art Rare (Star ★×1) → `rarities/icons/star/1.png`
- Crown Rare (Crown ♛×1) → `rarities/icons/crown/1.png`

### Sets

`sets/icons/{SET}.png` and `sets/logos/{SET}.png`

`{SET}` is the set code exactly as it appears in `sets.json`.

---

## Looking up paths from the database

The [ptcgp-data](https://github.com/Vociferix/ptcgp-data) SQLite database exposes a view for each image category. Each view returns an ID and a `path` column whose value is the relative path within this repository.

| View | Join key | Path formula |
|---|---|---|
| `card_version_images` | `card_version_id` | `cards/{set_code}/{number:03}.png` |
| `pack_art` | `pack_id` | `packs/art/{set_code}/{subtitle_lower}.png` |
| `pack_logos` | `pack_id` | `packs/logos/{set_code}/{subtitle_lower}.png` |
| `set_icons` | `set_id` | `sets/icons/{set_code}.png` |
| `set_logos` | `set_id` | `sets/logos/{set_code}.png` |
| `rarity_icons` | `rarity_id` | `rarities/icons/{group_lower}/{count}.png` |
| `rarity_symbols` | `rarity_id` | `rarities/symbols/{group_lower}/{count}.png` |
| `element_icons` | `element_id` | `elements/icons/{element_lower}.png` |
| `element_symbols` | `element_id` | `elements/symbols/{element_lower}.png` |
| `promo_source_icons` | `promo_source_id` | `promo_sources/{source_lower}.png` |

Example — get the image path for every card in set A1:

```sql
SELECT cv.number, cvi.path
FROM card_versions cv
JOIN sets s ON s.id = cv.set_id
JOIN card_version_images cvi ON cvi.card_version_id = cv.id
WHERE s.code = 'A1'
ORDER BY cv.number;
```

To build a URL for use in a web app, prepend the raw content base URL:

```
https://raw.githubusercontent.com/Vociferix/ptcgp-images/main/{path}
```
