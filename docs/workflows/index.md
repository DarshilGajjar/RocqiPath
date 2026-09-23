# Workflows

Every workflow has the same shape in Python, on the command line and in
Studio:

| | Python | Command line |
|---|---|---|
| Run | `rp.align(inputs, output_dir, **settings)` | `rocqipath align INPUT… OUTPUT --setting value` |
| Settings | keywords, or `config=rp.AlignConfig(...)` | flags, or `--config settings.toml` |
| Nested settings | `valis__num_features=3000` | `--valis.num-features 3000` |
| All settings | `help(rp.AlignConfig)` | `rocqipath align --help-all` |

Settings files are TOML with the config's field names; nested settings are
tables:

```toml
# align.toml
backend = "orb"
target_magnification = 20.0
qc_enabled = true

[orb]
ransac_threshold = 10.0
```

`rocqipath list` shows each workflow and whether its extra is installed. The
pages that follow give each workflow's full reference, rendered from its
docstrings.
