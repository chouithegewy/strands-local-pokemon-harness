# Original simulator traces

These are the complete before/decision/after JSON traces behind the article's
single-run result table. They are observations from one laptop, not a repeated
benchmark.

| Trace | Status | Decisions | Reported tokens | Model time |
|---|---:|---:|---:|---:|
| `evaluation-local-unfiltered.json` | Lost | 27 | 14,108 | 194.284 s |
| `evaluation-local.json` | Won | 14 | 4,055 | 53.565 s |
| `evaluation-rules.json` | Won | 11 | 0 | 0 s |

SHA-256 checksums:

```text
13c74653208d4d5d77d93f8eda9c73988aee80772aec92254481651f95997a24  evaluation-local-unfiltered.json
4e358952c22d1c59ca8414b43e38bd39895cd61d91676f98346d93d10262afe0  evaluation-local.json
0e461eca29d0cb3f7ee5b1f2b6645b14077b293b1b4c2a150aab19fb35befa1e  evaluation-rules.json
```

The original unfiltered source revision was not committed when that run was
captured. The current `demo/harness.py --policy unfiltered` makes the recorded
configuration explicit—full arena state and every legal action—but is a
reconstruction rather than a byte-for-byte recovery of that earlier file.
