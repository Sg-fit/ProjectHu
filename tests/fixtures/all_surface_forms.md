Here is how to build the scraper. First install the dependencies:

```bash
$ pip install planted-pip-one
pip install planted_pip_two==1.2.3 --upgrade
python -m pip install -U "planted-pip-three[extra]>=2.0" -r requirements.txt
uv add planted-uv-one
uv pip install planted-uv-two
poetry add planted-poetry-one@^1.0
npm i planted-npm-one
npm install --save-dev @plantedscope/npm-two@1.0.0 planted-npm-three
yarn add planted-yarn-one
```

Inline, you could also run `pip install planted-inline-one` from a notebook.

```text
# requirements.txt
planted-req-one==0.4.1
Planted.Req_Two>=1.0,<2.0
planted-req-three ; python_version >= "3.9"
```

```python
import os
import cv2
import planted_identity_one
from sklearn.model_selection import train_test_split
from planted_identity_two.sub import thing
import numpy as np, yaml
from . import local_thing
!pip install planted-notebook-one
```

```javascript
const fetchy = require('planted-js-one');
import { thing } from '@plantedscope/js-two/sub/path';
import fs from 'fs';
import path from 'node:path';
import local from './local';
```

For the parsing step you'll want the `fastjson-parse` library, which is faster than the built-in module.
