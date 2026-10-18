# Third-party dependencies and services

The MIT license covers social-fetch's source. It does not relicense dependencies,
external services or downloaded media.

- [DDGS](https://github.com/deedy5/ddgs) provides public index lookups and is
  installed as a Python dependency. Its dependencies keep their upstream licenses.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) provides the allowlisted X, Facebook
  and Reddit extraction paths, and metadata extraction for Pinterest, Twitch
  clips, Snapchat Spotlight and public LinkedIn posts. It is an attributed
  dependency; the four secondary routes validate and stream the selected MP4
  through our own bounded HTTP transfer. It also provides the optional direct
  Instagram and TikTok fallback metadata. It is not used for our YouTube route.
- [Bluesky](https://docs.bsky.app/) and [Mastodon](https://docs.joinmastodon.org/)
  publish the public metadata/blob APIs used by their scoped native MP4 adapters.
- [FFmpeg](https://ffmpeg.org/legal.html) and ffprobe are system dependencies.
  Their license depends on the build installed by the user.
- [SnapYT](https://www.snapyt.app/), [SnapInsta.lc](https://snapinsta.lc/) and
  [TikWM](https://www.tikwm.com/) are external public services used by the
  YouTube, Instagram and TikTok adapters respectively. They are independent of
  this project and can change, rate limit or become unavailable.
- [FxEmbed](https://github.com/FxEmbed/FxEmbed) supplies the public FxTwitter API
  used by the X alternative. Its delivery stays on approved Twitter media hosts.
- [Cobalt](https://github.com/imputnet/cobalt/blob/main/docs/api.md) defines the
  optional YouTube relay API. Users must explicitly configure their own instance;
  this package includes no Cobalt server code and selects no hosted instance.
  Cobalt's upstream license is separate from this package's MIT license.

No third-party media, browser profile, cookies, credentials or service installation
is included. This project is unaffiliated with the platforms and relay services.
