from pathlib import Path
import json
import sys

TOKENS = ['$$', '$', '\\(', '\\)', '\\[', '\\]']


def scan_file(path: Path):
    s = path.read_text(encoding='utf-8')
    events = []
    stack = []  # (token, line, col)
    i = 0
    L = len(s)
    line = 1
    col = 1
    while i < L:
        ch = s[i]
        # handle newlines
        if ch == '\n':
            line += 1
            col = 1
            i += 1
            continue
        # escaped sequences \(
        if s.startswith('\\(', i) or s.startswith('\\)', i) or s.startswith('\\[', i) or s.startswith('\\]', i):
            token = s[i:i+2]
            # treat \( and \[ as opening, \) and \] as closing
            if token in ('\\(', '\\['):
                stack.append((token, line, col))
            else:
                if stack and ((stack[-1][0] == '\\(' and token == '\\)') or (stack[-1][0] == '\\[' and token == '\\]')):
                    stack.pop()
                else:
                    events.append({'type': 'invalid_nesting', 'token': token, 'line': line, 'col': col, 'context': get_line_context(s, line)})
            i += 2
            col += 2
            continue
        # dollar tokens
        if s.startswith('$$', i):
            token = '$$'
            if not stack or stack[-1][0] not in ('$', '$$'):
                stack.append((token, line, col))
            else:
                top = stack[-1][0]
                if top == token:
                    stack.pop()
                elif top == '$':
                    # $$ inside inline is invalid
                    events.append({'type': 'invalid_nesting', 'token': token, 'line': line, 'col': col, 'context': get_line_context(s, line)})
                else:
                    stack.append((token, line, col))
            i += 2
            col += 2
            continue
        if ch == '$':
            token = '$'
            if not stack or stack[-1][0] not in ('$', '$$'):
                stack.append((token, line, col))
            else:
                top = stack[-1][0]
                if top == token:
                    stack.pop()
                elif top == '$$':
                    events.append({'type': 'invalid_nesting', 'token': token, 'line': line, 'col': col, 'context': get_line_context(s, line)})
                else:
                    stack.append((token, line, col))
            i += 1
            col += 1
            continue
        # normal char
        i += 1
        col += 1
    # end
    unmatched = [{'token': t, 'line': l, 'col': c, 'context': get_line_context(s, l)} for (t, l, c) in stack]
    return {'events': events, 'unmatched': unmatched}


def get_line_context(s: str, line_no: int):
    lines = s.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no-1][:200]
    return ''


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: typst_token_checker.py <input.typ> <output.json>')
        sys.exit(2)
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2])
    report = scan_file(inp)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Wrote report to', out)
