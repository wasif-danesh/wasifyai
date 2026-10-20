# wasifyai-model3d

Make a 3D model from a picture, or from words through a picture (ADR-0080, stages TD1 and TD2).
Desktop only: the 3D engine (`pixal3d.cpp` with the Pixal3D single-view models) is a component the
engine installs on request (`services/api/src/wasifyai_api/desktop_model3d.py`). This package holds
the models a person made (a small SQLite file and the GLB files under the app's data folder), the
picture checks, the routes of the screen and the `model3d.generate` action. A finished model is a
creation of its own kind, `model3d`, found by its words in My creations.
