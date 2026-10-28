"""Verify feeds, keep five CC release versions, and verify actual OSS deletion.

The current stable updater target occupies one of the five slots. This script
never deletes Dashboard files, root indexes, or objects outside releases/vX.Y.Z/.
"""
import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, unquote

PREFIX = 'releases/'
BASE = 'https://cc-launcher-dist.oss-cn-shanghai.aliyuncs.com/'
VERSION = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)')
KEEP = 5


def version_key(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError('Invalid version: ' + str(value))
    return tuple(map(int, value.split('.')))


def select_releases(catalog, latest):
    if not isinstance(catalog, list) or not catalog:
        raise ValueError('Empty or invalid release catalog; no deletion allowed')
    entries = {}
    for entry in catalog:
        version_key(entry['version'])
        if entry['version'] in entries:
            raise ValueError('Duplicate release version')
        entries[entry['version']] = entry
    stable = latest['version']
    version_key(stable)
    entries.setdefault(stable, dict(latest, prerelease=False))
    ordered = sorted(entries, key=version_key, reverse=True)
    kept = ordered[:KEEP]
    if stable not in kept:
        kept[-1] = stable
    return [entries[v] for v in kept]


def object_version(key):
    if not key.startswith(PREFIX):
        return None
    directory, sep, filename = key[len(PREFIX):].partition('/')
    if not sep or not directory.startswith('v') or not VERSION.fullmatch(directory[1:]):
        return None
    if '..' in filename.split('/') or '\\' in filename:
        return None
    return directory[1:]


def obsolete_objects(keys, kept):
    return [key for key in keys if (version := object_version(key)) is not None and version not in kept]


def url_key(url, version):
    if not isinstance(url, str) or not url.startswith(BASE):
        raise ValueError('Unexpected download host')
    parsed = urlsplit(url)
    key = unquote(parsed.path.lstrip('/'))
    if parsed.query or parsed.fragment or object_version(key) != version:
        raise ValueError('Download path does not match release version')
    return key


def read_json(bucket, key):
    raw = bucket.get_object(key).read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Release metadata too large')
    return json.loads(raw)


def verify_downloads(bucket, records):
    verified = set()
    for record in records:
        platforms = record.get('platforms')
        if not isinstance(platforms, dict) or not platforms:
            raise ValueError('Release has no platform downloads')
        for platform in platforms.values():
            url = platform['url']
            key = url_key(url, record['version'])
            if key in verified:
                continue
            size = int(bucket.head_object(key).headers['Content-Length'])
            if size <= 0:
                raise ValueError('Empty package: ' + key)
            with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30) as response:
                if response.status != 200 or int(response.headers['Content-Length']) != size:
                    raise ValueError('Public download mismatch: ' + key)
            verified.add(key)
    return len(verified)


def enforce(bucket, iterator, apply=False):
    catalog = read_json(bucket, PREFIX + 'releases.json')
    latest = read_json(bucket, PREFIX + 'latest.json')
    selected = select_releases(catalog, latest)
    kept = {entry['version'] for entry in selected}
    objects = list(iterator(bucket, prefix=PREFIX))
    obsolete = obsolete_objects([obj.key for obj in objects], kept)
    versions = {object_version(obj.key) for obj in objects} - {None}
    report = {'dryRun': not apply, 'prefix': PREFIX, 'keep': sorted(kept, key=version_key, reverse=True),
              'stable': latest['version'], 'beforeVersions': sorted(versions, key=version_key, reverse=True),
              'obsoleteVersions': sorted(versions - kept, key=version_key, reverse=True),
              'obsoleteObjects': obsolete,
              'obsoleteBytes': sum(obj.size for obj in objects if obj.key in set(obsolete))}
    report_path = Path('oss-retention-report.json')
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    report['verifiedDownloads'] = verify_downloads(bucket, selected + [latest])
    # Always verify the actual channel again before mutation. A changed channel
    # must be planned again; never delete against a stale snapshot.
    if read_json(bucket, PREFIX + 'latest.json') != latest or read_json(bucket, PREFIX + 'releases.json') != catalog:
        raise ValueError('Release channel changed during validation')
    if apply:
        if selected != catalog:
            bucket.put_object(PREFIX + 'releases.json', json.dumps(selected, ensure_ascii=False).encode('utf-8'),
                              headers={'Content-Type': 'application/json', 'Cache-Control': 'no-cache'})
            if read_json(bucket, PREFIX + 'releases.json') != selected:
                raise ValueError('Catalog update verification failed')
        # Single deletes surface AccessDenied reliably; a batch HTTP 200 can
        # still leave undeleted objects. Never swallow that failure.
        for key in obsolete:
            bucket.delete_object(key)
        remaining = list(iterator(bucket, prefix=PREFIX))
        pending = obsolete_objects([obj.key for obj in remaining], kept)
        if pending:
            raise ValueError('Deletion incomplete: ' + json.dumps(pending))
        after = {object_version(obj.key) for obj in remaining} - {None}
        if after != kept:
            raise ValueError('Retained version folders do not match the catalog')
        report['afterVersions'] = sorted(after, key=version_key, reverse=True)
        report['removedObjects'] = len(obsolete)
    report['verified'] = True
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    import oss2
    endpoint = os.environ['OSS_ENDPOINT'].removeprefix('https://').removeprefix('http://').rstrip('/')
    name = os.environ['OSS_BUCKET']
    if f'https://{name}.{endpoint}/' != BASE:
        raise ValueError('Unexpected OSS destination')
    bucket = oss2.Bucket(oss2.Auth(os.environ['OSS_ACCESS_KEY_ID'], os.environ['OSS_ACCESS_KEY_SECRET']),
                         'https://' + endpoint, name, connect_timeout=30)
    enforce(bucket, oss2.ObjectIteratorV2, options.apply)
