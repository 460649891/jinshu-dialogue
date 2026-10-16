"""Check local links and heading fragments in the public project documentation."""
import argparse
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from package_source import DOC_FILES, ROOT_FILES

LINK = re.compile(r'\[[^\]\n]*\]\(([^)\n]+)\)')


def prose(text):
    """Examples inside fenced code are not rendered Markdown links."""
    fence = None
    result = []
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value[0]
            elif value[0] == fence:
                fence = None
            result.append('')
        else:
            result.append('' if fence else line)
    return '\n'.join(result)


def headings(text):
    result, counts = set(), {}
    for line in prose(text).splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)\s*#*$', line)
        if not match:
            continue
        title = re.sub(r'`([^`]+)`', r'\1', match.group(1))
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug + (f'-{count}' if count else ''))
    return result


def check_links(root):
    root = Path(root).resolve()
    documents = DOC_FILES | {name for name in ROOT_FILES if name.endswith('.md')} | {'.github/pull_request_template.md'}
    errors = []
    checked = 0
    for name in sorted(documents):
        document = root / name
        if not document.is_file():
            errors.append(f'{name}: 缺少公开文档')
            continue
        for number, line in enumerate(prose(document.read_text(encoding='utf-8')).splitlines(), 1):
            for match in LINK.finditer(line):
                value = match.group(1).strip()
                value = value[1:value.index('>')] if value.startswith('<') and '>' in value else value.split(' "', 1)[0]
                url = urlsplit(value)
                if url.scheme or url.netloc:
                    continue
                checked += 1
                target = (document.parent / unquote(url.path)).resolve() if url.path else document
                if not target.is_relative_to(root) or not target.is_file():
                    errors.append(f'{name}:{number}: 本地链接不存在或越过仓库边界：{value}')
                elif url.fragment and target.suffix.lower() == '.md':
                    if unquote(url.fragment) not in headings(target.read_text(encoding='utf-8')):
                        errors.append(f'{name}:{number}: 标题锚点不存在：{value}')
    return checked, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    checked, errors = check_links(args.root)
    for error in errors:
        print(error)
    print(f'Documentation: {checked} local links, {len(errors)} errors')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
