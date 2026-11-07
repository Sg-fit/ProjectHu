Sure! The simplest approach is to keep a running total in a dictionary.

First, read the file line by line and split each line on commas. Store the `count`
variable outside the loop, and call `main()` at the end. If you want to install this
on a server, just copy the script and run it with Python 3.12 or newer.

You can use the built-in `json` module and the `pathlib` library for this; no extra
dependencies are needed. A list comprehension keeps it short:

```python
import json
import sys
from pathlib import Path
from collections import Counter

def main():
    counts = Counter(line.split(",")[0] for line in Path(sys.argv[1]).read_text().splitlines())
    print(json.dumps(counts, indent=2))

if __name__ == "__main__":
    main()
```

Run it with `python count.py data.csv`. The package of results is printed as JSON, and
you can pipe it to another program. Make sure the `data.csv` file exists first.
