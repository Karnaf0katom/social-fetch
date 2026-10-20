"""Download a public video with social-fetch NETWORK URL [-o DIRECTORY].

Search public posts, read account/comment samples, or manage saved download jobs.
All operations print JSON; use NETWORK --help for download options.
"""
import argparse
import json
from pathlib import Path
import sys

from social_fetch.client import Client, SOURCES, doctor
from social_fetch import __version__
from social_fetch.social_sources import DOMAINS, LABELS, download_link

NETWORKS = tuple(DOMAINS)


def _social_output(network, url, directory):
    link = download_link(url)
    if link.platform != network:
        raise ValueError(f'Use a public {LABELS[network]} video post link with the {network} command.')
    directory = directory.expanduser().absolute()
    if directory.exists() and not directory.is_dir():
        raise ValueError('Choose an output directory, not a filename, with -o/--output.')
    return directory / f'{network}-{link.identity}.mp4'


def _download(client, url, *, timeout, out=None, wait=False, image=False):
    client._timeout(timeout)
    suffixes = {'.jpg', '.jpeg', '.png', '.webp'} if image else {'.mp4'}
    if out is not None:
        out = out.expanduser()
        if out.exists() or out.is_symlink() or out.suffix.lower() not in suffixes:
            kind = 'image' if image else 'MP4'
            raise ValueError(f'Choose a new {kind} output filename before downloading.')
    result = client.download_image(url) if image else client.download(url)
    if wait or out is not None:
        job_id = result['id']
        try:
            result = client.wait(job_id, timeout=timeout)
        except TimeoutError as error:
            result = {**client.status(job_id), 'timed_out': True, 'message': str(error)}
        if out is not None and result['status'] == 'ready':
            result = client.export(job_id, out)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--data-dir', type=Path, help='Persistent jobs/media directory (default: ~/.local/share/social-fetch)')
    sub = parser.add_subparsers(dest='action', required=True)
    networks = []
    for network in NETWORKS:
        command = sub.add_parser(network, help=f'Download one public {LABELS[network]} video to a directory',
                                 description=f'Download one public {LABELS[network]} video, wait, and export a checked MP4.')
        command.add_argument('url', help='Public video post URL')
        command.add_argument('-o', '--output', type=Path, default=Path('.'), metavar='DIRECTORY',
                             help='Output directory (default: current directory); existing files are preserved')
        command.add_argument('--timeout', type=float, default=900,
                             help='Maximum wait in seconds (default: 900); saved jobs continue after a timeout')
        networks.append(command)
    sub.add_parser('doctor', help='Check installed dependencies without a network request')
    search = sub.add_parser('search', help='Find indexed public posts or creator accounts')
    search.add_argument('query')
    search.add_argument('--source', choices=SOURCES, default='social')
    search.add_argument('--accounts', action='store_true')
    search.add_argument('--page', type=int, choices=range(10), default=0)
    search.add_argument('--count', type=int, choices=range(1, 41), default=12)
    account = sub.add_parser('account', help='Read a small public account sample')
    account.add_argument('url')
    account.add_argument('--count', type=int, choices=range(1, 6), default=5)
    comments = sub.add_parser('comments', help='Read a bounded public Instagram or Reddit comment sample')
    comments.add_argument('url')
    comments.add_argument('--count', type=int, choices=range(1, 101),
                          help='Reddit: 1–20 (default 5); Instagram: 1–100 (default 50)')
    links = sub.add_parser('links', help='Find linked resources in post/comment text or JSON from any platform')
    inputs = links.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--text', help='Post, caption or comment text')
    inputs.add_argument('--input', type=Path, help='UTF-8 text/JSON file; use - to read stdin (maximum 2 MiB)')
    links.add_argument('--source-url', help='Original post URL, retained with every discovered reference')
    links.add_argument('--count', type=int, choices=range(1, 101), default=20)
    links.add_argument('--download', action='store_true', help='Save up to 20 references and their readable text; no recursive crawl')
    resource = sub.add_parser('resource', help='Download a linked public document, GitHub resource, file or page')
    resource.add_argument('url')
    resource.add_argument('--archive', action='store_true', help='Save a GitHub repository ZIP instead of its README')
    resource.add_argument('--max-mib', type=int, choices=range(1, 21), default=20)
    resource.add_argument('--timeout', type=float, default=60)
    download = sub.add_parser('download', help='Queue one selected post; media must pass checks before ready')
    download.add_argument('url')
    download.add_argument('--wait', action='store_true', help='Wait for the saved job to finish')
    download.add_argument('--timeout', type=float, default=900, help='Maximum wait in seconds; the saved job continues after a timeout')
    download.add_argument('--out', type=Path, help='Wait and export a checked MP4 to this filename')
    image = sub.add_parser('image', help='Queue one selected native Reddit image')
    image.add_argument('url')
    image.add_argument('--wait', action='store_true', help='Wait for the saved job to finish')
    image.add_argument('--timeout', type=float, default=900, help='Maximum wait in seconds')
    image.add_argument('--out', type=Path, help='Wait and export a checked image')
    status = sub.add_parser('status', help='Read a saved job without resubmitting')
    status.add_argument('job_id')
    export = sub.add_parser('export', help='Copy a checked, ready job into a local production source folder')
    export.add_argument('job_id')
    export.add_argument('--out', type=Path, required=True)
    for command in (*networks, search, account, comments, links, resource, download, image, status, export):
        command.add_argument('--namespace', default='social-cli', help='Production namespace; use the same value for later status')
        command.add_argument('--save', type=Path, help='Save metadata JSON (no media tokens) to a production source ledger')
    args = parser.parse_args(argv)
    try:
        if args.action == 'doctor':
            result = doctor()
            print(json.dumps(result, indent=2))
            return 0 if result['status'] == 'ready' else 1
        client = Client(args.data_dir, namespace=args.namespace)
        if args.action in NETWORKS:
            out = _social_output(args.action, args.url, args.output)
            result = _download(client, args.url, timeout=args.timeout, out=out, wait=True)
        elif args.action == 'search':
            result = client.search(args.query, source=args.source, accounts=args.accounts, page=args.page, count=args.count)
        elif args.action == 'account':
            result = client.account(args.url, count=args.count)
        elif args.action == 'comments':
            result = client.comments(args.url, count=args.count)
        elif args.action == 'links':
            payload = args.text
            if args.input:
                if str(args.input) == '-':
                    payload = sys.stdin.read(2 * 1024**2 + 1)
                else:
                    with args.input.open(encoding='utf-8') as source:
                        payload = source.read(2 * 1024**2 + 1)
                if len(payload.encode('utf-8')) > 2 * 1024**2:
                    raise ValueError('Use a text/JSON input of at most 2 MiB.')
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    if args.input.suffix.lower() == '.json':
                        raise ValueError('The supplied JSON file is invalid.') from None
            result = client.resources(payload, source_url=args.source_url, download=args.download, limit=args.count)
        elif args.action == 'resource':
            result = client.resource(args.url, archive=args.archive, max_bytes=args.max_mib * 1024**2, timeout=args.timeout)
        elif args.action in {'download', 'image'}:
            result = _download(client, args.url, timeout=args.timeout, out=args.out,
                               wait=args.wait, image=args.action == 'image')
        elif args.action == 'status':
            result = client.status(args.job_id)
        else:
            result = client.export(args.job_id, args.out)
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            args.save.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        failed = {'failed', 'cancelled', 'unavailable', 'access_required', 'not_found', 'rate_limited',
                  'blocked', 'too_large', 'needs_selection', 'unsupported', 'use_social_reader', 'integrity_error'}
        return 1 if result.get('status') in failed or args.action == 'links' and result.get('status') == 'partial' or result.get('timed_out') else 0
    except KeyboardInterrupt:
        message = ('Operation interrupted.' if args.action == 'comments' else
                   'Observation stopped. Saved download jobs continue; use status to reconnect.')
        print(json.dumps({'status': 'interrupted', 'message': message}))
        return 130
    except Exception as error:
        from social_fetch.web_search import SearchBusy, SearchUnavailable
        message = str(error) if isinstance(error, (ValueError, SearchBusy, SearchUnavailable, RuntimeError, TimeoutError)) else 'Social discovery or download is unavailable.'
        print(json.dumps({'status': 'failed', 'message': message}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
