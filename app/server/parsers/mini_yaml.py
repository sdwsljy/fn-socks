# -*- coding: utf-8 -*-
"""极简 YAML 子集解析器。

仅覆盖 Clash 配置实际用到的语法：块级映射/序列、注释、单双引号字符串、
普通标量、流式数组 [a, b] 与流式映射 {k: v}。
优先尝试导入 PyYAML（fnOS 可能预装 python3-yaml），失败则用本实现。
"""
import re

try:  # pragma: no cover - 渐进增强
    import yaml as _yaml
    HAS_PYYAML = True
except Exception:
    _yaml = None
    HAS_PYYAML = False


def load(text, use_pyyaml=True):
    if use_pyyaml and HAS_PYYAML:
        try:
            return _yaml.safe_load(text)
        except Exception:
            pass
    return MiniYaml(text).parse()


class ParseError(Exception):
    pass


def _strip_comment(line):
    out = []
    in_s = None
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_s:
            out.append(c)
            if c == in_s and (i == 0 or line[i - 1] != "\\"):
                in_s = None
        elif c in ("'", '"'):
            in_s = c
            out.append(c)
        elif c == "#":
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _split_key_value(line):
    in_s = None
    depth = 0
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if in_s:
            if c == in_s and (i == 0 or line[i - 1] != "\\"):
                in_s = None
        elif c in ("'", '"'):
            in_s = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == ":" and depth == 0:
            if i + 1 < n and line[i + 1] == " ":
                return line[:i].strip(), line[i + 2:].strip()
            if i + 1 == n:
                return line[:i].strip(), None
        i += 1
    return None, None


def _parse_scalar(s):
    s = s.strip()
    if s == "":
        return None
    if s in ("null", "Null", "NULL", "~"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if inner == "":
            return []
        return [_parse_scalar(x) for x in _split_flow(inner)]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        result = {}
        if inner:
            for kv in _split_flow(inner):
                k, v = _split_key_value(kv)
                if k is not None:
                    result[_unquote(k)] = _parse_scalar(v)
        return result
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            pass
    if re.fullmatch(r"-?\d+\.\d+", s):
        try:
            return float(s)
        except ValueError:
            pass
    return s


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        inner = s[1:-1]
        if s[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner.replace("''", "'")
    return s


def _split_flow(s):
    parts = []
    in_s = None
    depth = 0
    cur = []
    prev = None
    for c in s:
        if in_s:
            cur.append(c)
            if c == in_s and prev != "\\":
                in_s = None
        elif c in ("'", '"'):
            in_s = c
            cur.append(c)
        elif c in "[{":
            depth += 1
            cur.append(c)
        elif c in "]}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        prev = c
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


class MiniYaml(object):
    def __init__(self, text):
        self.lines = []
        for raw in text.splitlines():
            line = _strip_comment(raw)
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            content = line.strip()
            if content == "---":
                continue
            self.lines.append((indent, content))

    def parse(self):
        if not self.lines:
            return {}
        obj, _ = self._parse_block(0, self.lines[0][0])
        return obj

    def _parse_block(self, idx, indent):
        result = {}
        i = idx
        n = len(self.lines)
        while i < n:
            cur_indent, content = self.lines[i]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise ParseError("unexpected indent at line %d" % (i + 1))
            if content.startswith("-"):
                if result:
                    raise ParseError("mixed map/seq at line %d" % (i + 1))
                return self._parse_seq(i, indent)
            key, rest = _split_key_value(content)
            if key is None:
                raise ParseError("cannot parse line %d: %s" % (i + 1, content))
            k = _unquote(key)
            if rest is None or rest == "":
                if i + 1 < n and self.lines[i + 1][0] > indent:
                    child, i = self._parse_block(i + 1, self.lines[i + 1][0])
                    result[k] = child
                else:
                    result[k] = None
                    i += 1
                continue
            if rest.startswith("-") and (len(rest) == 1 or rest[1] == " "):
                seq, i = self._parse_inline_seq(i, rest, cur_indent)
                result[k] = seq
                continue
            result[k] = _parse_scalar(rest)
            i += 1
        return result, i

    def _parse_seq(self, idx, indent):
        items = []
        i = idx
        n = len(self.lines)
        while i < n:
            cur_indent, content = self.lines[i]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise ParseError("unexpected indent at line %d" % (i + 1))
            if not content.startswith("-"):
                break
            rest = content[1:].strip()
            if rest == "":
                if i + 1 < n and self.lines[i + 1][0] > cur_indent:
                    child_indent = self.lines[i + 1][0]
                    child, i = self._parse_block(i + 1, child_indent)
                    items.append(child)
                else:
                    items.append(None)
                    i += 1
                continue
            if rest.startswith("-") and (len(rest) == 1 or rest[1] == " "):
                item, i = self._parse_inline_seq(i, rest, cur_indent)
                items.append(item)
                continue
            key, value = _split_key_value(rest)
            if key is not None:
                item = {}
                if value is None or value == "":
                    item[_unquote(key)] = None
                    i += 1
                else:
                    item[_unquote(key)] = _parse_scalar(value)
                    i += 1
                if i < n and self.lines[i][0] > cur_indent:
                    child, i = self._parse_block(i, self.lines[i][0])
                    if isinstance(child, dict):
                        item.update(child)
                items.append(item)
                continue
            items.append(_parse_scalar(rest))
            i += 1
        return items, i

    def _parse_inline_seq(self, idx, first_rest, cur_indent):
        items = []
        if len(first_rest) > 1:
            items.append(_parse_scalar(first_rest[1:].strip()))
        i = idx + 1
        n = len(self.lines)
        while i < n:
            cindent, content = self.lines[i]
            if cindent <= cur_indent:
                break
            if content.startswith("-") and (len(content) == 1 or content[1] == " "):
                rest = content[1:].strip()
                if rest == "":
                    items.append(None)
                else:
                    items.append(_parse_scalar(rest))
                i += 1
            else:
                break
        return items, i


def extract_proxies(text):
    try:
        data = load(text)
    except ParseError:
        return None
    if not isinstance(data, dict):
        return None
    proxies = data.get("proxies")
    if isinstance(proxies, list):
        return proxies
    return []
