# Fresh-install smoke results — 0.4.0

Run started **2026-10-20T11:45:46Z** on Linux with Python 3.11.15,
yt-dlp 2026.8.19, ddgs 9.14.4, and FFmpeg/ffprobe 8.0.1.

Installed a non-editable wheel built by `pip install /absolute/path/to/social-fetch`
in a new temporary virtual environment. Commands ran outside the checkout with
fresh job storage, a fresh HOME and a minimal environment, using public services
without credentials. All 16 installed Python files matched the local release
source byte for byte. `social-fetch --version` reported 0.4.0; `doctor` reported
all four dependencies ready; `pip check` passed. The offline suite passed
**516 tests** before the live run.

**12/12 work; no failed samples.** Each result below came from the installed
`social-fetch NETWORK URL -o DIRECTORY` command. At most two commands ran at once,
with a 240-second observation timeout. No retries, injected failures or forced
fallbacks were used. “Works” means exit code 0, a ready job, an exported MP4,
an independently matching receipt SHA-256, successful ffprobe inspection and
a successful one-second FFmpeg decode. All samples have audio except Mastodon.

| Network | Result / reason | Duration | Dimensions | Exported bytes | Receipt route |
| --- | --- | ---: | --- | ---: | --- |
| `youtube` | Works: checked export and decode | 15.209s | 1080 × 1920 | 4,370,979 | `snapyt` |
| `instagram` | Works: checked export and decode | 13.367s | 720 × 1280 | 3,377,242 | `snapinsta` |
| `tiktok` | Works: checked export and decode | 27.467s | 540 × 960 | 2,748,534 | `tikwm` |
| `x` | Works: checked export and decode | 6.873s | 1280 × 720 | 1,025,857 | `x_syndication` |
| `facebook` | Works: checked export and decode | 44.331s | 1080 × 1080 | 12,474,253 | `facebook_extractor` |
| `reddit` | Works: checked export and decode | 52.067s | 1080 × 1920 | 21,644,453 | `reddit_embed_rapidsave` |
| `bluesky` | Works: checked export and decode | 29.737s | 1920 × 1080 | 6,688,967 | `bluesky_appview` |
| `pinterest` | Works: checked export and decode | 33.879s | 720 × 1280 | 5,094,001 | `pinterest_extractor` |
| `twitch` | Works: checked export and decode | 32.099s | 1920 × 1080 | 16,299,421 | `twitch_extractor` |
| `snapchat` | Works: checked export and decode | 4.642s | 480 × 880 | 583,697 | `snapchat_extractor` |
| `linkedin` | Works: checked export and decode | 161.866s | 1428 × 720 | 5,663,647 | `linkedin_extractor` |
| `mastodon` | Works: checked export and decode | 38.850s | 1692 × 1484 | 1,287,545 | `mastodon_rest` |

## Public samples

| Command | URL supplied |
| --- | --- |
| `youtube` | https://www.youtube.com/shorts/6F0e3UHcQkg |
| `instagram` | https://www.instagram.com/reel/C_bnaTAO2Ll/ |
| `tiktok` | https://www.tiktok.com/@patroxofficial/video/6742501081818877190 |
| `x` | https://x.com/buildingisgreen/status/1793226866335076588/video/2 |
| `facebook` | https://www.facebook.com/watch/?v=10155529876156509 |
| `reddit` | https://www.reddit.com/r/mercedes_benz/comments/1uwp60q/ |
| `bluesky` | https://bsky.app/profile/bsky.app/post/3l3vgf77uco2g |
| `pinterest` | https://www.pinterest.com/pin/298856125290563650/ |
| `twitch` | https://clips.twitch.tv/FaintLightGullWholeWheat |
| `snapchat` | https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYYWtidGhudGZpAX1TKn0JAX1TKnXJAAAAAA |
| `linkedin` | https://www.linkedin.com/posts/the-mathworks_2_what-is-mathworks-cloud-center-activity-7151241570371948544-4Gu7/ |
| `mastodon` | https://mastodon.social/@mastodon/116839714185151652 |

The X sample selects `/video/2`; its filename retains that selection. The YouTube
sample is a Short. The Mastodon sample is silent gifv, and establishes no new
coverage for posts with audio. The longest sample is the 162-second LinkedIn
video; all others are under one minute. These are dated sample results, not a
guarantee that every public post or external service will remain available.

## Export hashes

| Network | SHA-256 of exported MP4 |
| --- | --- |
| `youtube` | `eeb395a7802d87c69c2a37b68511b4722f40f4aa3fdaa6bef0859e1c62d0ace8` |
| `instagram` | `f2374051dc3e3110c74b658226578469c64370f608acb5caf5254fd6ba4f78d6` |
| `tiktok` | `13222d719676dd80b804321f07a91b013c585a673615af8fe9e859cc339b07a7` |
| `x` | `db5a1e0e04a24d7b2a483b766b1efec58e635863ee1208547c7cf79fac96c60c` |
| `facebook` | `64708e1dcc19f2af4b0ee54af9e1e1ed021b3ebea68d407eb29591b916f5d989` |
| `reddit` | `5f275697cc812e836318b05fe82f88baba41b895e6d77e0d78ae5b051635ee4e` |
| `bluesky` | `f3c3fecb52a9e3d9f7c88d6510baadde425c0444f66efd624eca881661b1d862` |
| `pinterest` | `9aac322848f48e4e9c95b19bf5a95defb6b5e9862bdb462d583ed9de592fc18c` |
| `twitch` | `4057cefed283eb3547d7d6ac5f8eed55f0443cd38270a20d8ba7fc2ed25a5b59` |
| `snapchat` | `d404e7d75eabf2c1645ef75b4bc9f8078549615d30101f0cf1bd405959d86cdb` |
| `linkedin` | `831619cfccd2256cd1281db728670004dde819d5535053c0728ce0dbfa591752` |
| `mastodon` | `a1e61bc1b63df48e61721a39515ddcd65e41b6d1bc964d69a24a747012e73364` |

## Reproduce

From the local checkout, choose a temporary directory on a filesystem with at
least 9 GiB free for one active download (18 GiB for two). The example uses
`/var/tmp` because this host’s `/tmp` did not have enough free space.

```bash
repo_dir="$PWD"
smoke_dir=$(mktemp -d /var/tmp/social-fetch-smoke-XXXXXX)
python3 -m venv "$smoke_dir/venv"
"$smoke_dir/venv/bin/python" -m pip install "$repo_dir"
cd "$smoke_dir"
"$smoke_dir/venv/bin/social-fetch" --version
"$smoke_dir/venv/bin/social-fetch" doctor
"$smoke_dir/venv/bin/social-fetch" --help
# Repeat with each network and corresponding public URL from the table:
"$smoke_dir/venv/bin/social-fetch" --data-dir "$smoke_dir/jobs" \
  youtube "https://www.youtube.com/shorts/6F0e3UHcQkg" \
  -o "$smoke_dir/exports" --timeout 240 --namespace v040-smoke
```

Run downloads in a fresh environment when comparing availability. The output JSON
includes the job ID, route, measured media metadata, hash and export filename.
A failed command returns nonzero; preserve its sanitized message, failure stage
and route attempts when recording a new result. On timeout, observe the saved job
with the same data directory and namespace before submitting more work. Downloaded
media, temporary delivery URLs, worker logs and environment files are excluded
from this repository.
