# Sony A7 PMCA artwork

The main mark comes from the user-supplied `sony-a7-pmca-concept-1.svg` at the repository root. `sony-a7-pmca.svg` preserves its shapes and colors, with a 1024-pixel output size for rasterization.

- `sony-a7-pmca.svg`: editable vector artwork.
- `sony-a7-pmca.png`: 1024×1024 transparent raster used inside the GUI.
- `sony-a7-pmca.icns`: macOS application icon.
- `make-icons.sh`: regenerate the PNG and ICNS using CoreGraphics and the local PNG-container packer.
- `pack-icons.py`: creates a modern ICNS container from the validated PNG representations, without system temporary-file caches.
- `render-icon.swift`: a window-free sRGB renderer matching the selected SVG's circles, dash pattern, Bézier paths, and colors. If you change that SVG, update this geometry or export the updated SVG with an SVG renderer. This avoids the native SVG decoder's restricted temporary-file cache in automation.

From the repository root:

```bash
sh assets/make-icons.sh
```

The default preview build has no USB capture entitlement. The experiment was rejected at runtime in this environment and is documented in `docs/usb-access-status.md`; it is not shipped as a working build configuration.
