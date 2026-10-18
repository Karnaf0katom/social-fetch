"""AI-callable social discovery and download commands using the footage app's owners.

Examples: python3 -m social_fetch.social_cli search 'interior design' --source instagram --accounts
          python3 -m social_fetch.social_cli account https://www.instagram.com/nasa/
          python3 -m social_fetch.social_cli download PUBLIC_POST --namespace my-production
          python3 -m social_fetch.social_cli status JOB_ID --namespace my-production
"""
import argparse
import json
from pathlib import Path

from social_fetch.client import Client, SOURCES, doctor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, help='Persistent jobs/media directory (default: ~/.local/share/social-fetch)')
    sub = parser.add_subparsers(dest='action', required=True)
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
    download = sub.add_parser('download', help='Queue one selected post; media must pass checks before ready')
    download.add_argument('url')
    download.add_argument('--wait', action='store_true', help='Wait for the saved job to finish')
    download.add_argument('--timeout', type=float, default=900, help='Maximum wait in seconds; the saved job continues after a timeout')
    download.add_argument('--out', type=Path, help='Wait and export a checked MP4 to this filename')
    status = sub.add_parser('status', help='Read a saved job without resubmitting')
    status.add_argument('job_id')
    export = sub.add_parser('export', help='Copy a checked, ready job into a local production source folder')
    export.add_argument('job_id')
    export.add_argument('--out', type=Path, required=True)
    for command in (search, account, download, status, export):
        command.add_argument('--namespace', default='social-cli', help='Production namespace; use the same value for later status')
        command.add_argument('--save', type=Path, help='Save metadata JSON (no media tokens) to a production source ledger')
    args = parser.parse_args(argv)
    try:
        if args.action == 'doctor':
            result = doctor()
            print(json.dumps(result, indent=2))
            return 0 if result['status'] == 'ready' else 1
        client = Client(args.data_dir, namespace=args.namespace)
        if args.action == 'search':
            result = client.search(args.query, source=args.source, accounts=args.accounts, page=args.page, count=args.count)
        elif args.action == 'account':
            result = client.account(args.url, count=args.count)
        elif args.action == 'download':
            client._timeout(args.timeout)
            if args.out and (args.out.exists() or args.out.is_symlink() or args.out.suffix.lower() != '.mp4'):
                raise ValueError('Choose a new MP4 output filename before downloading.')
            result = client.download(args.url)
            if args.wait or args.out:
                job_id = result['id']
                try:
                    result = client.wait(job_id, timeout=args.timeout)
                except TimeoutError as error:
                    result = {**client.status(job_id), 'timed_out': True, 'message': str(error)}
                if args.out and result['status'] == 'ready':
                    result = client.export(job_id, args.out)
        elif args.action == 'status':
            result = client.status(args.job_id)
        else:
            result = client.export(args.job_id, args.out)
        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            args.save.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('status') in {'failed', 'cancelled'} or result.get('timed_out') else 0
    except KeyboardInterrupt:
        print(json.dumps({'status': 'interrupted', 'message': 'Observation stopped. Saved download jobs continue; use status to reconnect.'}))
        return 130
    except Exception as error:
        from social_fetch.web_search import SearchBusy, SearchUnavailable
        message = str(error) if isinstance(error, (ValueError, SearchBusy, SearchUnavailable, RuntimeError, TimeoutError)) else 'Social discovery or download is unavailable.'
        print(json.dumps({'status': 'failed', 'message': message}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
