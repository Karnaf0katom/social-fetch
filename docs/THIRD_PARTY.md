# Third-party dependencies and services

The MIT license covers social-fetch's source. It does not relicense dependencies,
external services or downloaded media.

- [DDGS](https://github.com/deedy5/ddgs) provides public index lookups and is
  installed as a Python dependency. Its dependencies keep their upstream licenses.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) provides the allowlisted X and Facebook
  extraction paths, and metadata extraction for Pinterest, Twitch
  clips, Snapchat Spotlight and public LinkedIn posts. It is an attributed
  dependency; the four secondary routes validate and stream the selected MP4
  through our own bounded HTTP transfer. It also provides the Instagram
  alternative's metadata. It is not used for our YouTube route.
- [Bluesky](https://docs.bsky.app/) and [Mastodon](https://docs.joinmastodon.org/)
  publish the public metadata/blob APIs used by their scoped native MP4 adapters.
- [FFmpeg](https://ffmpeg.org/legal.html) and ffprobe are system dependencies.
  Their license depends on the build installed by the user.
- [SnapYT](https://www.snapyt.app/), [SnapInsta.lc](https://snapinsta.lc/) and
  [TikWM](https://www.tikwm.com/) are external public services used by the
  YouTube, Instagram and TikTok adapters respectively. They are independent of
  this project and can change, rate limit or become unavailable.
- [SSSTik](https://ssstik.io/) supplies TikTok alternative selected-post media
  through its public form and fresh anonymous form cookies. Delivery is bound to
  the selected numeric video ID on the approved CDN.
- [FxEmbed](https://github.com/FxEmbed/FxEmbed) supplies the FixupX selected embed
  used by the X alternative. Its delivery stays on approved Twitter media hosts;
  the earlier FxTwitter API route is retained only as historical code/evidence.
- [Reddit embeds](https://embed.reddit.com/) identify selected posts, native media
  and current comment bodies. [RapidSave](https://rapidsave.com/) supplies the
  merged video/audio delivery route; both source streams must match the selected
  native media. [Arctic Shift](https://arctic-shift.photon-reddit.com/) supplies
  bounded comment ID/permalink discovery, which can omit recent comments.
- [Cobalt](https://github.com/imputnet/cobalt/blob/main/docs/api.md) defines the
  optional YouTube relay API. Users must explicitly configure their own instance;
  this package includes no Cobalt server code and selects no hosted instance.
  Cobalt's upstream license is separate from this package's MIT license.

No third-party media, browser profile, cookies, credentials or service installation
is included. This project is unaffiliated with the platforms and relay services.
