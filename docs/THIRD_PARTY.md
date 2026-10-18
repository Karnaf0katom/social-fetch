# Third-party dependencies and services

The MIT license covers social-fetch's source. It does not relicense dependencies,
external services or downloaded media.

- [DDGS](https://github.com/deedy5/ddgs) provides public index lookups and is
  installed as a Python dependency. Its dependencies keep their upstream licenses.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) provides the allowlisted X, Facebook
  and Reddit extractors and is installed separately as a dependency.
- [FFmpeg](https://ffmpeg.org/legal.html) and ffprobe are system dependencies.
  Their license depends on the build installed by the user.
- [SnapYT](https://www.snapyt.app/), [SnapInsta.lc](https://snapinsta.lc/) and
  [TikWM](https://www.tikwm.com/) are external public services used by the
  YouTube, Instagram and TikTok adapters respectively. They are independent of
  this project and can change, rate limit or become unavailable.

No third-party media, browser profile, cookies, credentials or service installation
is included. This project is unaffiliated with the platforms and relay services.
