# 3D model credits

## concept-coupe.glb

"Car Concept" by Eric Chadwick, (c) 2024 Darmstadt Graphics Group GmbH.

- Licence: Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/
- Source: Khronos glTF Sample Assets, https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/CarConcept
- The Khronos model was started from a public-domain model, "Free Concept Car 004" by Unity Fan.

Changes made for this app (the script is `tools/prepare-concept-coupe.mjs`):

- Removed the Khronos Group and 3D Commerce logos: the number plate, the tyre sidewall lettering, the emblems
  on the wheels, brakes, mirrors and trim, and the steering wheel emblem. Those marks are not covered by the
  model's licence.
- Kept one paint set and dropped the material variants. The app repaints the body and the interior to match
  each listing, and makes the paint less mirror-like so the colour reads.
- Replaced the refractive glass with simple tinted glass.
- Removed parts that are hidden on a turntable (engine, axles, pedals, under-hood panels).
- Simplified the mesh to about 128,000 triangles and resized the textures.

It is an original concept car, not a model of any production car. This app is not affiliated with or endorsed by
the model's authors or the Khronos Group.
