"""Build corpus/top_pypi.json, corpus/top_npm.json and corpus/control_packages.json.

Inputs (committed for provenance):
  corpus/sources/top-pypi-packages.min.json  - hugovk.dev/top-pypi-packages, 30-day downloads
Run:  python scripts/build_reference_lists.py

The control set is ONLY for shim false-positive measurement and is never mixed
into the generation corpus. Real packages are stratified by popularity rank so
the false-positive rate is not trivially zero; typo variants are deterministic
single edits of real names, excluding any variant that is itself a top-15000
package. No variant is ever registered anywhere - they are looked up, only.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from als.names import normalize  # noqa: E402

SEED = 20261106

# Hand-curated npm reference list (no equivalent public top-N JSON is pinned here).
# Every entry is checked against the live registry by `als eval-shim`; a wrong entry shows up there.
TOP_NPM = """
lodash react react-dom express axios chalk commander debug moment uuid typescript webpack babel-core
@babel/core @babel/preset-env eslint prettier jest mocha chai yargs fs-extra glob rimraf mkdirp
async bluebird underscore request body-parser cors dotenv jsonwebtoken bcrypt bcryptjs mongoose
mysql2 pg redis ioredis socket.io ws node-fetch cross-env nodemon ts-node rxjs vue next nuxt
@angular/core svelte jquery classnames prop-types styled-components tailwindcss postcss autoprefixer
sass less vite rollup esbuild semver minimist inquirer ora dayjs date-fns luxon zod joi yup ajv
winston pino morgan helmet passport multer sharp jimp canvas puppeteer playwright cheerio jsdom
marked markdown-it highlight.js handlebars ejs pug nunjucks graphql apollo-server @apollo/client
knex sequelize typeorm prisma @prisma/client firebase aws-sdk @aws-sdk/client-s3 stripe twilio
nodemailer csv-parse papaparse xlsx pdfkit pdf-lib qrcode argon2 express-rate-limit compression
cookie-parser serialport noble @abandonware/noble onnxruntime-node fluent-ffmpeg wavesurfer.js
simple-peer wrtc socket.io-client got superagent chokidar concurrently husky lint-staged
""".split()


def main() -> None:
    src = json.loads((ROOT / "corpus" / "sources" / "top-pypi-packages.min.json").read_text(encoding="utf-8"))
    names = [normalize(r["project"]) for r in src["rows"]]
    (ROOT / "corpus" / "top_pypi.json").write_text(json.dumps({
        "source": "https://hugovk.dev/top-pypi-packages/top-pypi-packages.min.json",
        "source_last_update": src.get("last_update"),
        "ranking": "downloads, last 30 days",
        "packages": names,
    }, indent=0), encoding="utf-8")
    (ROOT / "corpus" / "top_npm.json").write_text(json.dumps({
        "source": "hand-curated (scripts/build_reference_lists.py)", "packages": TOP_NPM}, indent=0), encoding="utf-8")

    rng = random.Random(SEED)
    strata = [(0, 1000, 50), (1000, 5000, 30), (5000, 15000, 20)]
    real = []
    for lo, hi, k in strata:
        for i in sorted(rng.sample(range(lo, min(hi, len(names))), k)):
            real.append({"name": names[i], "ecosystem": "pypi", "rank": i + 1})
    npm_real = [{"name": n, "ecosystem": "npm"} for n in rng.sample(TOP_NPM, 15)]

    top_set = set(names)
    typos = []
    for r in rng.sample(real[:80], 50):
        n = r["name"]
        for _ in range(20):
            op = rng.choice(["drop", "swap", "double", "sub"])
            i = rng.randrange(1, len(n)) if len(n) > 2 else 0
            if op == "drop":
                v = n[:i] + n[i + 1:]
            elif op == "swap" and i < len(n) - 1:
                v = n[:i] + n[i + 1] + n[i] + n[i + 2:]
            elif op == "double":
                v = n[:i] + n[i] + n[i:]
            else:
                v = n[:i] + rng.choice("abcdefghijklmnopqrstuvwxyz") + n[i + 1:]
            v = normalize(v.strip("-"))
            if v and v != n and v not in top_set and v[0].isalnum():
                typos.append({"name": v, "ecosystem": "pypi", "of": n, "edit": op})
                break

    (ROOT / "corpus" / "control_packages.json").write_text(json.dumps({
        "_note": "Shim false-positive control set. Never mixed into generation prompts. Typo variants are "
                 "looked up only; nothing here is ever registered on any registry.",
        "seed": SEED,
        "real": real + npm_real,
        "typo": typos,
    }, indent=1), encoding="utf-8")
    print(f"top_pypi: {len(names)}, top_npm: {len(TOP_NPM)}, control real: {len(real) + len(npm_real)}, typo: {len(typos)}")


if __name__ == "__main__":
    main()
