"""Lexical structure of TS/TSX/JS source for the source adapter (H2).

There is no TypeScript parser in the API environment, and inspection must
never execute the source it inspects. This module is a small, deliberately
conservative lexer: it knows where comments, string/template/regex
literals and code are, which is enough to

- match brackets and JSX tags without being fooled by a `{` inside a
  string, a comment or a regex (`/^[^@]+@[^@]{2,}$/`);
- find import declarations, JSX opening/closing tags and array elements;
- classify an occurrence of a business fact as bindable text (a string
  literal or JSX text) or not (comments, identifiers, attribute values
  such as className/href).

Every transformation built on it is still applied as an exact-once
replacement (plan.py) and the export's own build (tsc/vite) re-checks the
result, so a construct this lexer misreads fails closed — it can never
produce a silently wrong edit. Known limits (documented, fail closed): an
apostrophe in JSX text that is closed by another apostrophe on the same
line is read as a string; regex literals are recognised by the preceding
token only.
"""

import re
from dataclasses import dataclass

_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%~^")
_REGEX_KEYWORDS = ("return", "typeof", "case", "do", "else", "in", "of", "void", "yield", "await", "delete")
_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {v: k for k, v in _OPEN.items()}


class ScanError(ValueError):
    """The source has a structure this lexer does not handle safely."""


@dataclass(frozen=True)
class StringToken:
    start: int  # index of the opening quote
    end: int  # index AFTER the closing quote
    quote: str
    value: str  # raw content between the quotes (escapes not decoded)


@dataclass(frozen=True)
class Scan:
    text: str
    masked: str  # same length: comments -> spaces, literal contents -> "_"
    strings: tuple[StringToken, ...]

    def is_code(self, index: int) -> bool:
        return self.masked[index] == self.text[index] and self.text[index] not in "\"'`"


def _prev_significant(masked: list[str], index: int) -> tuple[str, str]:
    """(previous non-space char, previous identifier word) in code."""
    j = index - 1
    while j >= 0 and masked[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return "", ""
    k = j
    while k >= 0 and (masked[k].isalnum() or masked[k] in "_$"):
        k -= 1
    return masked[j], "".join(masked[k + 1 : j + 1])


def scan(text: str) -> Scan:  # noqa: C901 — one lexer state machine
    out = list(text)
    strings: list[StringToken] = []
    n = len(text)
    i = 0
    # "template" (inside `...`) or "brace" (a { opened in code, possibly
    # inside a template expression).
    stack: list[str] = []

    def mask(a: int, b: int, char: str = "_") -> None:
        for k in range(a, b):
            if text[k] != "\n":
                out[k] = char

    while i < n:
        c = text[i]
        if stack and stack[-1] == "template":
            if c == "\\":
                mask(i, min(i + 2, n))
                i += 2
                continue
            if c == "`":
                stack.pop()
                i += 1
                continue
            if c == "$" and i + 1 < n and text[i + 1] == "{":
                stack.append("brace")
                i += 2
                continue
            mask(i, i + 1)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            end = n if end == -1 else end
            mask(i, end, " ")
            i = end
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                raise ScanError("unterminated block comment")
            mask(i, end + 2, " ")
            i = end + 2
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            if j < n and text[j] == c:
                strings.append(StringToken(i, j + 1, c, text[i + 1 : j]))
                mask(i + 1, j)
                i = j + 1
                continue
            i += 1  # an apostrophe in JSX text: plain text, not a string
            continue
        if c == "`":
            stack.append("template")
            i += 1
            continue
        if c == "{":
            stack.append("brace")
        elif c == "}":
            if stack and stack[-1] == "brace":
                stack.pop()
        elif c == "/":
            prev, word = _prev_significant(out, i)
            if (prev == "" or prev in _REGEX_PRECEDERS or word in _REGEX_KEYWORDS) and text[i + 1 : i + 2] not in (
                ">",
                "/",
            ):
                j, in_class = i + 1, False
                while j < n and text[j] != "\n":
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == "[":
                        in_class = True
                    elif text[j] == "]":
                        in_class = False
                    elif text[j] == "/" and not in_class:
                        break
                    j += 1
                if j < n and text[j] == "/":
                    mask(i + 1, j)
                    i = j + 1
                    continue
        i += 1
    if "template" in stack:
        raise ScanError("unterminated template literal")
    return Scan(text=text, masked="".join(out), strings=tuple(strings))


def matching(s: Scan, open_index: int) -> int:
    """Index of the bracket closing the one at `open_index` (code only)."""
    opener = s.masked[open_index]
    if opener not in _OPEN:
        raise ScanError(f"not an opening bracket at {open_index}")
    depth = 0
    for k in range(open_index, len(s.masked)):
        ch = s.masked[k]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
            if depth == 0:
                if _CLOSE[ch] != opener:
                    raise ScanError(f"mismatched bracket at {k}")
                return k
    raise ScanError(f"unbalanced bracket opened at {open_index}")


def enclosing(s: Scan, index: int, opener: str) -> int | None:
    """Index of the innermost unclosed `opener` bracket before `index`
    (other bracket kinds in between are skipped over)."""
    depth = {"(": 0, "[": 0, "{": 0}
    for k in range(index - 1, -1, -1):
        ch = s.masked[k]
        if ch in _CLOSE:
            depth[_CLOSE[ch]] += 1
        elif ch in _OPEN:
            if depth[ch] == 0:
                if ch == opener:
                    return k
                continue
            depth[ch] -= 1
    return None


def array_elements(s: Scan, open_index: int) -> list[tuple[int, int]]:
    """(start, end) spans of the top-level elements of the `[` at open_index."""
    close = matching(s, open_index)
    elements, depth, start = [], 0, open_index + 1
    for k in range(open_index + 1, close):
        ch = s.masked[k]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif ch == "," and depth == 0:
            elements.append((start, k))
            start = k + 1
    elements.append((start, close))
    return [(a, b) for a, b in elements if s.text[a:b].strip()]


# --- Imports -----------------------------------------------------------------------

_IMPORT = re.compile(
    r"^import\s+(?:(?P<clause>[^;]*?)\s+from\s+)?(?P<q>[\"'])(?P<spec>[^\"'\n]+)(?P=q)[ \t]*;?[ \t]*\n",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class ImportDecl:
    start: int
    end: int  # after the trailing newline
    clause: str | None  # None for a side-effect import
    spec: str
    statement: str


def imports(s: Scan) -> list[ImportDecl]:
    return [
        ImportDecl(m.start(), m.end(), m.group("clause"), m.group("spec"), m.group(0))
        for m in _IMPORT.finditer(s.text)
        if s.is_code(m.start())
    ]


def imported_names(clause: str | None) -> list[str]:
    """Local names bound by an import clause (`X, { a, type B as C }`)."""
    if not clause:
        return []
    names: list[str] = []
    named = re.search(r"\{([^}]*)\}", clause)
    default = (clause[: named.start()] if named else clause).strip().rstrip(",").strip()
    if default.startswith("* as "):
        names.append(default[5:].strip())
    elif default:
        names.append(default.removeprefix("type ").strip())
    if named:
        for part in named.group(1).split(","):
            part = part.strip().removeprefix("type ").strip()
            if part:
                names.append(part.split(" as ")[-1].strip())
    return names


# --- JSX ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JsxTag:
    name: str
    start: int  # index of "<"
    end: int  # index AFTER ">"
    self_closing: bool
    attrs: str  # raw attribute text


def jsx_open_tags(s: Scan, name: str) -> list[JsxTag]:
    tags = []
    for m in re.finditer(rf"<{re.escape(name)}(?=[\s/>])", s.masked):
        k, depth = m.end(), 0
        while k < len(s.masked):
            ch = s.masked[k]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            k += 1
        if k >= len(s.masked):
            raise ScanError(f"unterminated <{name}> tag")
        self_closing = s.masked[k - 1] == "/"
        tags.append(JsxTag(name, m.start(), k + 1, self_closing, s.text[m.end() : k - 1 if self_closing else k]))
    return tags


def jsx_close_tag(s: Scan, tag: JsxTag) -> tuple[int, int]:
    """(start, end) of the `</name>` closing `tag` (nested same-name tags counted)."""
    if tag.self_closing:
        raise ScanError(f"<{tag.name}> is self-closing")
    opens = {t.start for t in jsx_open_tags(s, tag.name) if not t.self_closing}
    closes = {m.start() for m in re.finditer(rf"</{re.escape(tag.name)}\s*>", s.masked)}
    depth = 0
    for pos in sorted(p for p in opens | closes if p >= tag.start):
        depth += 1 if pos in opens else -1
        if depth == 0:
            return pos, s.masked.index(">", pos) + 1
    raise ScanError(f"<{tag.name}> at {tag.start} is never closed")


def enclosing_tag(s: Scan, index: int, name: str) -> JsxTag | None:
    """The innermost `<name>` element whose content contains `index`."""
    best = None
    for tag in jsx_open_tags(s, name):
        if tag.self_closing or tag.start >= index:
            continue
        close, _ = jsx_close_tag(s, tag)
        if index < close and (best is None or tag.start > best.start):
            best = tag
    return best


def jsx_attr(tag: JsxTag, attr: str) -> str | None:
    """A static string attribute value (`attr="v"`), None if absent/dynamic."""
    m = re.search(rf"(?:^|\s){re.escape(attr)}\s*=\s*([\"'])(.*?)\1", tag.attrs, re.DOTALL)
    return m.group(2) if m else None


def jsx_has_attr(tag: JsxTag, attr: str) -> bool:
    return re.search(rf"(?:^|\s){re.escape(attr)}(?=[\s=/>]|$)", tag.attrs) is not None


# --- Text positions ------------------------------------------------------------------

# Attribute/property names whose string values are machine values, never
# visitor-facing text (a business fact is never bound inside them).
NON_TEXT_ATTRS = frozenset(
    {
        "className",
        "class",
        "id",
        "href",
        "src",
        "srcSet",
        "key",
        "htmlFor",
        "name",
        "type",
        "rel",
        "as",
        "value",
        "defaultValue",
        "to",
        "target",
        "style",
        "autoComplete",
        "inputMode",
        "role",
        "method",
        "action",
        "lang",
        "dir",
        "crossOrigin",
        "sizes",
        "media",
        "poster",
        "data-testid",
        "form",
        "pattern",
        "placeholder",
    }
)
NON_TEXT_KEYS = frozenset(
    {
        "value",
        "href",
        "src",
        "rel",
        "key",
        "id",
        "className",
        "path",
        "to",
        "type",
        "as",
        "crossOrigin",
        "sizes",
        "media",
        "lang",
        "charSet",
        "property",
        "icon",
        "poster",
        "video",
        "image",
        "url",
        "slug",
        "anchor",
        "hash",
    }
)
_NON_TEXT_PREFIXES = ("/", "http:", "https:", "#", "./", "../", "@/", "mailto:", "tel:")


def string_context(s: Scan, token: StringToken) -> tuple[str, str | None]:
    """How a string literal is used: ("attr", name) for `name="..."`,
    ("key", name) for `name: "..."`, ("import", None), ("json-key", None)
    or ("other", None)."""
    lo = max(0, token.start - 80)
    before = s.masked[lo : token.start]
    m = re.search(r"([A-Za-z_$][\w$-]*)\s*=\s*$", before)
    if m:
        return "attr", m.group(1)
    m = re.search(r"([A-Za-z_$][\w$]*|\"[^\"]*\"|'[^']*')\s*:\s*$", s.text[lo : token.start])
    if m:
        return "key", m.group(1).strip("\"'")
    if re.search(r"\b(?:from|import)\s*\(?\s*$", before) or re.search(r"\brequire\s*\(\s*$", before):
        return "import", None
    if s.masked[token.end : token.end + 4].lstrip().startswith(":"):
        return "json-key", None
    return "other", None


def is_text_string(s: Scan, token: StringToken) -> bool:
    """A string literal a visitor can read (not a machine value)."""
    kind, name = string_context(s, token)
    if kind in ("import", "json-key"):
        return False
    if kind == "attr" and name in NON_TEXT_ATTRS:
        return False
    if kind == "key" and name in NON_TEXT_KEYS:
        return False
    value = token.value.strip()
    return bool(value) and not value.startswith(_NON_TEXT_PREFIXES)


def jsx_text_runs(s: Scan) -> list[tuple[int, int]]:
    """Spans of JSX text: code runs that follow a JSX tag's `>` and end at
    the next `<` or `{`. A `>` that is a comparison/arrow is excluded."""
    runs = []
    for m in re.finditer(r">([^<>{}]+)(?=[<{])", s.masked):
        a, b = m.start(1), m.end(1)
        if not s.text[a:b].strip():
            continue
        if s.masked[max(0, m.start() - 1) : m.start() + 1] == "=>":
            continue
        # the `>` must close a JSX tag: the nearest `<` before it opens a tag
        lt = s.masked.rfind("<", 0, m.start())
        if lt == -1 or not re.match(r"</?[A-Za-z][\w.:-]*|<>|</>", s.masked[lt : lt + 40]):
            continue
        # `useState<Status>(` / `FormEvent<T>`: a type argument, not a tag
        if lt > 0 and (s.masked[lt - 1].isalnum() or s.masked[lt - 1] in "_$."):
            continue
        runs.append((a, b))
    return runs


def is_word_boundary(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")
