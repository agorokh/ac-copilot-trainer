# Windows Game Point launcher (UI kit)

Recreation of the **Game Point** desktop launcher (default 620×360) in the
Racing Atelier language. Utilitarian: opens to status + controls.

`index.html` — **Start** toggles between recovery (sidecar stopped) and ready
states. Status is a coloured field + the verbatim probe word; the one start
action is the brass field. Composes `Panel` (brackets) · `StatusField` ·
`StatusRow` · `Button` · `BrandMark`. Never render secrets — the token row shows
configured / missing, never the value.
