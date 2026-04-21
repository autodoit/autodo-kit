from pathlib import Path
import sys

def main(path):
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    print('dollar_count=', s.count('$'))
    print('double_count=', s.count('$$'))
    idxs = [i for i, c in enumerate(s) if c == '$']
    for idx in idxs[:20]:
        ctx = s[max(0, idx - 40): idx + 40]
        print('---', idx, '---')
        print(ctx.replace('\n', '\\n'))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: check_merged_typ.py <file>')
        sys.exit(1)
    main(sys.argv[1])
