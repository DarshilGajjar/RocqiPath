# Adding a workflow

This walks through a complete, small workflow: measuring the tissue fraction
of each image. Adding a workflow takes two pieces:

- **A config** in the owning package's `config.py`.
- **A function** in `rocqipath/api.py`.

The CLI command, Studio form and docs follow automatically. (The code on this
page is executed by `tests/test_docs_examples.py`, so it stays correct.)

## 1. The config

Settings are a dataclass inheriting `BaseConfig`. Document **every** field in
the `Parameters` section. That text becomes the CLI help, the Studio tooltip
and the API reference.

```python
from dataclasses import dataclass, field

from rocqipath._internal.base_config import ADVANCED, BaseConfig


@dataclass
class MeasureTissueConfig(BaseConfig):
    """Settings for ``measure_tissue``.

    Parameters
    ----------
    threshold : float
        Grey level (0-255) below which a pixel counts as tissue.
    downsample : int
        Measure on every n-th pixel for speed.
    """

    threshold: float = 220.0
    downsample: int = field(default=4, metadata=ADVANCED)

    def __post_init__(self) -> None:
        """Validate settings as soon as they are set."""
        if not 0 < self.threshold < 255:
            raise ValueError("threshold must be between 0 and 255")
```

## 2. The workflow

The function receives resolved `inputs` (a list of `Item`), an existing
`output_dir` and a validated `config`. It returns the produced items and a
summary. Import heavy dependencies inside the function.

```python
import json

from rocqipath.registry import InputSpec, Item, workflow


@workflow(
    "measure_tissue",
    config=MeasureTissueConfig,
    extra="viz",
    inputs=InputSpec(kind="images", roles=("region", "core", "patch")),
)
def measure_tissue(inputs, output_dir, *, config):
    """Measure the fraction of each image covered by tissue.

    Parameters
    ----------
    inputs : path, list of paths, or Result
        Images, or an earlier result whose regions, cores or patches are measured.
    output_dir : path
        A ``tissue_fraction.json`` is written here.
    config : MeasureTissueConfig, optional
        Settings, or give fields as keywords.

    Returns
    -------
    Result
        One ``"measurement"`` item; ``summary`` maps image names to fractions.
    """
    import numpy as np
    from PIL import Image

    fractions = {}
    for item in inputs:
        grey = np.asarray(Image.open(item.path).convert("L"))[:: config.downsample, :: config.downsample]
        fractions[item.path.name] = round(float((grey < config.threshold).mean()), 4)
    report = output_dir / "tissue_fraction.json"
    report.write_text(json.dumps(fractions, indent=2))
    return [Item(sample_id="all", role="measurement", path=report)], fractions
```

In the package, the function goes in `api.py` (with its name added to
`__all__` and to `_WORKFLOWS` in `rocqipath/__init__.py`). The config goes in
the package's `config.py`, exported from its `__init__` and from
`rocqipath/__init__.py`.

## 3. Use it everywhere

```python
import numpy as np
from PIL import Image

import rocqipath as rp
from rocqipath.registry import get_workflow

image = np.full((64, 64, 3), 255, dtype=np.uint8)
image[:32] = 120                     # top half is "tissue"
Image.fromarray(image).save(tmp / "sample.png")

result = measure_tissue(tmp / "sample.png", tmp / "out", threshold=200)
assert result.summary == {"sample.png": 0.5}
assert (tmp / "out" / "rocqipath.json").exists()

# The same workflow is now a CLI command and a Studio form:
assert get_workflow("measure-tissue").cli_name == "measure-tissue"
```

`rocqipath measure-tissue sample.png out/ --threshold 200` now works, and
Studio lists "Measure tissue" with a threshold field.

## 4. Test it

- **Golden test:** add a call to `tests/golden/_calls.py` with a synthetic
  input in `tests/golden/_data.py`, then record its snapshot with
  `pytest tests/golden --update-golden`.
- **Frontend fixture:** regenerate it with
  `python -m rocqipath.studio.catalog > studio-web/src/test/workflows.json`.
- **Contract tests:** `tests/test_public_api.py` and
  `tests/test_config_compat.py` check the calling convention and that every
  field is documented.
