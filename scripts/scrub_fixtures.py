"""Turn raw recordings into fixtures that are safe to commit.

Raw recordings (scripts/sample_*.py) land in backend/tests/fixtures_raw/<platform>/, which is
git-ignored: they hold real people's ids, names, avatars and comments, and for logged-in
platforms the recording account's own data. This script writes a scrubbed copy to
backend/tests/fixtures/<platform>/, which the parser tests read and which is committed.

What it does, per platform rule set:
- user ids -> random numbers of the same length (consistent across files of one run, not
  derivable from the original); names -> 用户1, 用户2, ...; avatars -> one placeholder image;
  signatures, birthdays, schools and other personal text -> cleared; comment bodies and
  free-text descriptions -> placeholder text. Structure, types and formats are kept, so the
  parsers see the same shapes.
- every collected name and id is then replaced wherever else it appears (@mentions, URLs,
  medal names), and the output is checked for leftovers: any original name or id still present
  aborts the run without writing.
- lists of objects are cut to MAX_LIST entries to keep the fixtures small.

Usage:
  uv run --project backend python scripts/scrub_fixtures.py bilibili
Only platforms with a rule set below are accepted, so nothing is copied unscrubbed.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "backend" / "tests" / "fixtures_raw"
OUT = REPO / "backend" / "tests" / "fixtures"
MAX_LIST = 10


@dataclass(frozen=True)
class Rules:
    id_keys: frozenset[str]  # numeric user ids (int or digit string)
    name_keys: frozenset[str]  # user display names, wherever they appear
    user_parents: frozenset[str]  # objects whose plain `name` is a user's name
    avatar_keys: frozenset[str]
    avatar_placeholder: str
    clear_keys: frozenset[str]  # personal text: emptied
    clear_parents: frozenset[str]  # objects whose string fields are all emptied (school, profession)
    text_keys: dict[str, str]  # free text -> placeholder prefix; key or "parent.key"
    name_maps: frozenset[str] = field(default_factory=frozenset)  # {name: id} dicts (@mentions)
    fixed: dict[str, Any] = field(default_factory=dict)  # key -> constant (e.g. sex -> undisclosed)


RULES: dict[str, Rules] = {
    "bilibili": Rules(
        id_keys=frozenset({"mid", "mid_str", "uid", "pay_mid", "roomid", "room_id"}),
        name_keys=frozenset({"uname", "author"}),
        user_parents=frozenset({"owner", "card", "member", "members", "info"}),
        avatar_keys=frozenset({"face", "avatar", "upic", "uface", "user_cover"}),
        avatar_placeholder="https://i0.hdslb.com/bfs/face/member/noface.jpg",
        clear_keys=frozenset({"sign", "usign", "birthday"}),
        clear_parents=frozenset({"school", "profession"}),
        text_keys={"content.message": "示例评论", "desc": "示例简介", "description": "示例简介", "raw_text": "示例简介", "data.desc": "示例简介"},
        name_maps=frozenset({"at_name_to_mid"}),
        fixed={"sex": "保密"},
    ),
}


class Scrubber:
    def __init__(self, rules: Rules):
        self.r = rules
        self.ids: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.avatars: set[str] = set()
        self.text_n = 0

    # ---- pass 1: collect what identifies people ----------------------------

    def _is_name(self, parent: str, key: str) -> bool:
        return key in self.r.name_keys or (key == "name" and parent in self.r.user_parents)

    def collect(self, o: Any, parent: str = "") -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in self.r.id_keys and _id_like(v):
                    self._fake_id(str(v))
                elif self._is_name(parent, k) and isinstance(v, str) and v.strip():
                    self._fake_name(v)
                elif k in self.r.avatar_keys and _is_url(v) and _core(v) != _core(self.r.avatar_placeholder):
                    self.avatars.add(_core(v))  # the site's default "no face" image is not personal
                elif k in self.r.name_maps and isinstance(v, dict):
                    for n, i in v.items():
                        self._fake_name(n)
                        if _id_like(i):
                            self._fake_id(str(i))
                self.collect(v, k)
        elif isinstance(o, list):
            for x in o:
                self.collect(x, parent)

    def _fake_id(self, orig: str) -> str:
        if orig in ("0", "") or len(orig) < 3:
            return orig
        if orig not in self.ids:
            used = set(self.ids.values())
            while True:
                fake = str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(len(orig) - 1))
                if fake != orig and fake not in used:
                    break
            self.ids[orig] = fake
        return self.ids[orig]

    def _fake_name(self, orig: str) -> str:
        if orig not in self.names:
            self.names[orig] = f"用户{len(self.names) + 1}"
        return self.names[orig]

    # ---- pass 2: rewrite ---------------------------------------------------

    def rewrite(self, o: Any, parent: str = "") -> Any:
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                out[self._key(k)] = self._value(parent, k, v)
            return out
        if isinstance(o, list):
            items = o[:MAX_LIST] if len(o) > MAX_LIST and all(isinstance(x, dict) for x in o) else o
            return [self.rewrite(x, parent) for x in items]
        if isinstance(o, str):
            return self._replace_all(o)
        return o

    def _key(self, k: str) -> str:
        return self.names.get(k, self._replace_all(k))

    def _value(self, parent: str, k: str, v: Any) -> Any:
        r = self.r
        if k in r.id_keys and _id_like(v):
            fake = self.ids.get(str(v), str(v))
            return int(fake) if isinstance(v, int) else fake
        if self._is_name(parent, k) and isinstance(v, str) and v.strip():
            return self.names[v]
        if k in r.name_maps and isinstance(v, dict):
            return {self.names.get(n, n): (int(self.ids.get(str(i), str(i))) if isinstance(i, int) else self.ids.get(str(i), i)) for n, i in v.items()}
        if k in r.avatar_keys and _is_url(v):
            return r.avatar_placeholder
        if k in r.fixed and isinstance(v, str):
            return r.fixed[k]
        if (k in r.clear_keys or parent in r.clear_parents) and isinstance(v, str):
            return ""
        prefix = r.text_keys.get(f"{parent}.{k}") or r.text_keys.get(k)
        if prefix and isinstance(v, str) and v:
            self.text_n += 1
            return f"{prefix} {self.text_n}"
        return self.rewrite(v, k)

    def _replace_all(self, s: str) -> str:
        for orig, fake in self._name_order:
            if orig in s:
                s = s.replace(orig, fake)
        if self._avatar_re and self._avatar_re.search(s):  # copies in avatar frames, widgets, ...
            s = self._avatar_re.sub(self.r.avatar_placeholder, s)
        if self._id_re and self._id_re.search(s):
            s = self._id_re.sub(lambda m: self.ids[m.group(0)], s)
        return s

    def freeze(self) -> None:
        # longest first, so a name that contains another is replaced whole
        self._name_order = sorted(((o, f) for o, f in self.names.items() if len(o) >= 2), key=lambda p: -len(p[0]))
        long_ids = sorted((i for i in self.ids if len(i) >= 5), key=len, reverse=True)
        self._id_re = re.compile(r"(?<!\d)(" + "|".join(map(re.escape, long_ids)) + r")(?!\d)") if long_ids else None
        self._avatar_re = re.compile(r"(?:https?:)?//(?:" + "|".join(map(re.escape, sorted(self.avatars, key=len, reverse=True))) + ")") if self.avatars else None

    # ---- leak check --------------------------------------------------------

    def leaks(self, text: str) -> list[str]:
        found = [f"name {o!r}" for o, _ in self._name_order if o in text]
        found += [f"avatar {a}" for a in self.avatars if a in text]
        if self._id_re:
            found += sorted({f"id {m.group(0)}" for m in self._id_re.finditer(text)})
        return found


def _core(url: str) -> str:
    """URL without its scheme, so http://x, https://x and //x compare equal."""
    return url.split("//", 1)[-1]


def _is_url(v: Any) -> bool:
    return isinstance(v, str) and (v.startswith("http") or v.startswith("//"))


def _id_like(v: Any) -> bool:
    return (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, str) and v.isdigit())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("platform")
    a = ap.parse_args()
    rules = RULES.get(a.platform)
    if rules is None:
        sys.exit(f"no scrub rules for {a.platform!r} yet (have: {', '.join(RULES)}); add a Rules entry before committing its fixtures")
    src = RAW / a.platform
    files = sorted(src.glob("*.json"))
    if not files:
        sys.exit(f"no raw recordings in {src}; run the sample script first")

    s = Scrubber(rules)
    docs = {f.name: json.loads(f.read_text(encoding="utf-8")) for f in files}
    for d in docs.values():
        s.collect(d)
    s.freeze()
    out = {name: json.dumps(s.rewrite(d), ensure_ascii=False, indent=2) + "\n" for name, d in docs.items()}

    leaks = {name: s.leaks(text) for name, text in out.items()}
    leaks = {n: l for n, l in leaks.items() if l}
    if leaks:
        for n, l in leaks.items():
            print(f"LEAK {n}: {', '.join(l[:8])}{' …' if len(l) > 8 else ''}")
        sys.exit("refusing to write: originals still present; extend the rules for these fields")

    dst = OUT / a.platform
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name, text in out.items():
        (dst / name).write_text(text, encoding="utf-8")
        print(f"  {name:24} {(src / name).stat().st_size // 1024:5} KB -> {len(text.encode()) // 1024:4} KB")
    print(f"{a.platform}: {len(s.ids)} ids, {len(s.names)} names, {s.text_n} texts replaced -> {dst.relative_to(REPO)}")


if __name__ == "__main__":
    main()
