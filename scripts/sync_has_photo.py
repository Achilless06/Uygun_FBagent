"""One-shot: walk data/photos/ and set Product.has_photo to match disk reality.

Run after bulk-uploading photos via SSH (when the upload path bypassed the
admin route's has_photo flip). Idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import bindparam, text  # noqa: E402

from src import config, db  # noqa: E402

PHOTOS_DIR = ROOT / "data" / "photos"


def main() -> int:
    cfg = config.load()
    db.init_engine(cfg.database_url)

    on_disk = {
        p.stem for p in PHOTOS_DIR.glob("*.jpg")
    } | {p.stem for p in PHOTOS_DIR.glob("*.jpeg")} | {
        p.stem for p in PHOTOS_DIR.glob("*.png")
    }
    print(f"photos on disk: {len(on_disk)}")

    with db.session_scope() as s:
        db_codes = {r[0] for r in s.execute(text("SELECT code FROM products")).all()}
        valid_on_disk = sorted(on_disk & db_codes)
        print(f"matching DB codes: {len(valid_on_disk)}")

        # Reset everything to false, then flip true for present files.
        s.execute(text("UPDATE products SET has_photo = 0"))
        if valid_on_disk:
            stmt = text(
                "UPDATE products SET has_photo = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE code IN :codes"
            ).bindparams(bindparam("codes", expanding=True))
            s.execute(stmt, {"codes": valid_on_disk})

        cur = s.execute(text("SELECT COUNT(*) FROM products WHERE has_photo = 1"))
        print(f"products has_photo=1 after sync: {cur.scalar()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
