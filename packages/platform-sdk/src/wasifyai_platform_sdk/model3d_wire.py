"""The wire format of 3D jobs (ADR-0087, stage P3): the API's `RemoteModel3dEngine` and the
worker's handlers share these names. A picture and its cut-out, and the finished GLB, are files in
object storage; the numbers are `meta`."""

MATTE = "model3d.matte"  # a picture in (`picture`), its cut-out out (`cutout`)
GENERATE = "model3d.generate"  # a cut-out in (`cutout`), a GLB out (`glb`); params: seed, detail
KINDS = [MATTE, GENERATE]
COMPONENT = "model3d"  # the key of a worker's `components` entry
