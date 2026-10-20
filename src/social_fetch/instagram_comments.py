"""Read a public Instagram post's available comment sample without downloading media.

Uses the installed yt-dlp Instagram extractor. Instagram may expose only an initial
page; this command never describes that sample as all comments or expands replies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from social_fetch.instagram_web import post_code, shortcode_id
from social_fetch.social_resources import discover_resources


class _Quiet:
    # Extractor diagnostics can contain temporary URLs. Return a fixed error instead.
    def debug(self, *args):
        pass

    warning = error = debug


def _extract(url):
    from yt_dlp import YoutubeDL

    with YoutubeDL({'quiet': True, 'logger': _Quiet(), 'skip_download': True,
                    'getcomments': True, 'socket_timeout': 15,
                    'retries': 0, 'extractor_retries': 0}) as downloader:
        # Avoid media processing/probing and retain the platform's reported total.
        return downloader.extract_info(url, download=False, process=False)


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def read_comments(url, *, limit=50):
    """Return normalized evidence, including explicit partial/unavailable coverage."""
    code = post_code(url)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Choose a comment count between 1 and 100.')
    source = f'https://www.instagram.com/p/{code}/'
    result = {'schema_version': 1, 'platform': 'instagram', 'source_url': source,
              'shortcode': code, 'retrieved_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'method': 'yt-dlp public Instagram metadata', 'status': 'unavailable',
              'reported_total': None, 'fetched_count': 0, 'returned_count': 0,
              'complete': False, 'replies_expanded': False, 'pagination': False,
              'comments': [], 'linked_resources': [], 'resource_notice': None, 'gaps': []}
    try:
        info = _extract(source)
    except Exception:
        result['gaps'] = ['Public extraction failed; the comment count is unknown.']
        return result
    if not isinstance(info, dict):
        result['gaps'] = ['The extractor did not return post metadata.']
        return result
    identity = str(info.get('id', ''))
    if identity not in {code, shortcode_id(code)}:
        result['gaps'] = ['The extractor did not establish the requested post identity.']
        return result
    result['reported_total'] = _number(info.get('comment_count'))
    result['caption'] = info.get('description') if isinstance(info.get('description'), str) else None
    sources = [info]
    if isinstance(info.get('entries'), list):
        sources.extend(entry for entry in info['entries'] if isinstance(entry, dict))
    rows, seen = [], set()
    for item in sources:
        comments = item.get('comments')
        if not isinstance(comments, list):
            continue
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            text = comment.get('text')
            identifier = comment.get('id')
            if not isinstance(text, str) or not text.strip() or not isinstance(identifier, (str, int)):
                continue
            identifier = str(identifier)
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            rows.append({'id': identifier, 'text': text,
                         'author': comment.get('author') if isinstance(comment.get('author'), str) else None,
                         'like_count': _number(comment.get('like_count')),
                         'timestamp': _number(comment.get('timestamp'))})
    result.update(fetched_count=len(rows), returned_count=min(limit, len(rows)), comments=rows[:limit])
    if rows:
        result['status'] = 'partial'
        result['gaps'] = ['Initial comment sample only; remaining pages and replies were not collected.']
    elif result['reported_total'] == 0:
        result['status'] = 'empty'
        result['gaps'] = ['The public metadata reports zero comments; replies were not independently checked.']
    else:
        result['gaps'] = ['No readable comments were exposed; this does not mean the post has no comments.']
    for comment in result['comments']:
        comment['linked_resources'] = discover_resources({'comments': [comment]}, source_url=source)['resources']
    linked = discover_resources(result, source_url=source)
    result.update(linked_resources=linked['resources'],
                  resource_notice=linked['notice'] if linked['count'] else None)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='Public Instagram post or Reel URL')
    parser.add_argument('--count', type=int, default=50, help='Maximum returned comments, 1–100 (default: 50)')
    parser.add_argument('--out', type=Path, help='Save normalized JSON to a new file')
    args = parser.parse_args(argv)
    if args.out and (args.out.exists() or args.out.is_symlink()):
        parser.error('Choose a new output filename; existing evidence is never overwritten.')
    try:
        result = read_comments(args.url, limit=args.count)
    except ValueError as error:
        parser.error(str(error))
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x') as output:
            output.write(encoded)
    print(encoded, end='')
    return 1 if result['status'] == 'unavailable' else 0


if __name__ == '__main__':
    raise SystemExit(main())
