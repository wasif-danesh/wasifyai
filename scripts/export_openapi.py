"""Write the API's OpenAPI schema (incl. SSE event models) for TS type generation."""

import json
import sys
from pathlib import Path

from wasifyai_api.main import app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "packages/contracts-ts/openapi.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {out}")
