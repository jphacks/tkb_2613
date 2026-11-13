"""公的な公開データ（事前に取得した手元の表）を「X は Y」の知識として使う推定経路。

- 居住地域：国土地理院の避難所の表（施設名 → 区市町村）
- 勤務先名：国税庁の法人番号の表（本人が書いた名前 → 法人の正式名称）

公開データは本人についての事実ではない。本人との関係は、投稿に明示された言い回し
（「自宅近くの X」など）でだけ決め、公開データは「X は Y にある」という一般的な知識にだけ使う。
診断のたびに外部へ問い合わせることはしない。

経路の形は cross_post の居住地域と同じで、次の3つが揃ったときだけ推定する。
- 本人との関係：ある投稿（またはプロフィール文）に「自宅近くの X」「近所の X」などがある
- 橋渡し：別の投稿の手がかり（ランドマーク・掲示・地名）の値に X が出てくる
- 値：公開データの表で X が1つの区市町村だけにある（同じ名前が2つ以上の区市町村にあれば使わない）
"""

import re
from collections.abc import Sequence

from tkb_common.schemas import (
    ClaimAssessment,
    Clue,
    ClueType,
    EvidenceScope,
    Post,
    ProfileAttribute,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileStatus,
)
from tkb_engine.cross_post_facts import CrossPostFact, FactRole, forbidden_context
from tkb_engine.gazetteer import Gazetteer

# 本人の住まいとの関係を明示する言い回し。この後ろ（文の終わりまで）に施設名がある
OWNER_NEAR_HOME_RE = re.compile(
    r"(?:(?:自宅|家|うち)の?(?:すぐ)?(?:近く|近所|目の前|前|そば)|近所)の?"
)
# 言い回しの後ろで、抜き出して根拠に見せる長さ
OWNER_NEAR_HOME_WINDOW = 40
SENTENCE_END_RE = re.compile(r"[。！？!?\n]")
BRIDGE_CLUE_TYPES = frozenset({ClueType.LANDMARK, ClueType.NOTICE, ClueType.PLACE_TEXT})

# 根拠の確からしさ。言い回しの判定は cross_post の居住地域と同じ控えめな値、
# 表の対応（施設名 → 区市町村）は公的な表なので高めにする。経路の確からしさは弱いほうになる
OWNER_RELATION_CONFIDENCE = 0.65
OPEN_DATA_CONFIDENCE = 0.9

SHELTER_CITATION = (
    "出典：国土地理院「指定緊急避難場所・指定避難所データ」を加工して作成。"
    "最新でない場合や未掲載の場合があります（最新の状況は各市町村にご確認ください）"
)


def shelter_home_facts(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    owner_profile_text: str,
    gazetteer: Gazetteer,
) -> list[CrossPostFact]:
    """避難所の名前を橋渡しにした、居住地域の経路の材料。表がなければ空。"""
    if not gazetteer.shelters:
        return []
    anchors: list[tuple[str | None, str, str]] = [(p.post_id, p.text, "post_text") for p in posts]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    facts: list[CrossPostFact] = []
    for anchor_post_id, text, source in anchors:
        if forbidden_context(text):
            continue
        for excerpt, name, rows in _named_near_home(text, gazetteer):
            cities = {str(r["city"]) for r in rows}
            if len(cities) != 1:
                continue  # 同じ名前の施設が別の区市町村にもある
            city = next(iter(cities))
            bridge_id = f"home:shelter:{name}"
            facts.append(
                CrossPostFact(
                    anchor_post_id,
                    None,
                    FactRole.OWNER_RELATION,
                    name,
                    OWNER_RELATION_CONFIDENCE,
                    bridge_id,
                    True,
                    excerpt=excerpt,
                    source=source,
                )
            )
            facts.append(
                CrossPostFact(
                    None,
                    None,
                    FactRole.SPECIFIC_VALUE,
                    city,
                    OPEN_DATA_CONFIDENCE,
                    bridge_id,
                    excerpt=f"{name}は{city}の{_kind(rows)}（{SHELTER_CITATION}）",
                    source="open_data",
                )
            )
            facts.extend(_bridge_facts(posts, clues, anchor_post_id, name, bridge_id, gazetteer))
    return facts


def _named_near_home(
    text: str, gazetteer: Gazetteer
) -> list[tuple[str, str, list[dict[str, object]]]]:
    """(抜き出した文, 施設名, その名前の行)。言い回しのすぐ後ろに書かれた施設名だけ。"""
    found: dict[str, tuple[str, list[dict[str, object]]]] = {}
    for match in OWNER_NEAR_HOME_RE.finditer(text):
        window = text[match.end() : match.end() + OWNER_NEAR_HOME_WINDOW]
        window = SENTENCE_END_RE.split(window, maxsplit=1)[0]
        for name, rows in gazetteer.shelters_named_at(window).items():
            found.setdefault(name, (match.group(0) + window, rows))
    return [(excerpt, name, rows) for name, (excerpt, rows) in found.items()]


def _bridge_facts(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    anchor_post_id: str | None,
    name: str,
    bridge_id: str,
    gazetteer: Gazetteer,
) -> list[CrossPostFact]:
    """別の投稿の手がかり（ランドマーク・掲示・地名）に、同じ施設名が出てくるもの。"""
    text_by_post = {p.post_id: p.text for p in posts}
    facts = []
    for index, clue in enumerate(clues):
        if (
            clue.post_id == anchor_post_id
            or clue.post_id not in text_by_post
            or clue.type not in BRIDGE_CLUE_TYPES
            or forbidden_context(text_by_post[clue.post_id])
            or name not in gazetteer.shelters_named_at(clue.value)
        ):
            continue
        facts.append(
            CrossPostFact(
                clue.post_id,
                index,
                FactRole.BRIDGE,
                name,
                clue.confidence,
                bridge_id,
                excerpt=clue.value,
            )
        )
    return facts


def _kind(rows: list[dict[str, object]]) -> str:
    kinds = {k for r in rows for k in str(r.get("kind") or "").split("・") if k}
    return "・".join(sorted(kinds, reverse=True)) or "避難所"


# --- 勤務先名：法人番号の公表データ ---------------------------------------------

# 本人が名前を勤務先として明示する言い回し。名前は言い回しの後ろにある
EMPLOYER_PREFIX_RE = re.compile(
    r"(?:私の勤務先は|私の勤め先は|勤務先は|勤め先は|うちの会社は)(?P<tail>[^\s、。！？!?]+)"
)
# 名前が言い回しの前にあるもの（「X で働いてる」「X に勤めています」）
# 後ろに「人」「友達」などが続くもの（「X で働いてる人」）は、ほかの人のことなので除く
EMPLOYER_SUFFIX_RE = re.compile(
    r"(?:で働いて|に勤めて|で勤めて)(?:る|いる|います|ます)"
    r"(?!\s*(?:人|方|子|友達|友人|仲間|知り合い|知人|社員|みなさん|皆さん))"
)
# 「兄は X で働いてる」のように、ほかの人のことを書いた文は本人の勤務先にしない
THIRD_PARTY_SUBJECT_RE = re.compile(
    r"(?:父|母|兄|姉|弟|妹|夫|妻|旦那|嫁|彼氏|彼女|友達|友人|息子|娘|親|祖父|祖母|同僚|先輩|後輩)"
    r"(?:さん|ちゃん|くん)?(?:は|が|も)"
)
MAX_EMPLOYER_NAME_LENGTH = 30
SENTENCE_START_RE = re.compile(r"[。！？!?\n\s、]")
EMPLOYER_CONFIDENCE = 0.65
CORPORATION_CITATION = "出典：国税庁法人番号公表サイト（国税庁）の公表データを加工して作成"


def infer_registry_employer_claim(
    posts: Sequence[Post], owner_profile_text: str, gazetteer: Gazetteer
) -> ProfileItem | None:
    """本人が勤務先として書いた名前を、法人番号の表の正式名称に結ぶ。

    投稿（またはプロフィール文）で名前を勤務先として明示し、別の投稿にも同じ名前が書かれていて、
    正規化した名前が表の1つの法人だけに一致するときだけ推定する。部分一致はしない。
    本店所在地は使わない（勤務地とは限らない）。表がなければ None。
    """
    if gazetteer.corporations_path is None:
        return None
    anchors: list[tuple[str | None, str, str]] = [(p.post_id, p.text, "post_text") for p in posts]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    candidates: dict[str, list[ProfileEvidencePath]] = {}
    for anchor_post_id, text, source in anchors:
        if forbidden_context(text):
            continue
        for excerpt, written in _employer_names(text, gazetteer):
            legal = gazetteer.corporations_named(written)
            if len({number for number, _ in legal}) != 1:
                continue  # 同じ名前の法人が2つ以上ある（1つもないときは _employer_names が除く）
            name = legal[0][1]
            anchor_ref = ProfileEvidence(
                post_id=anchor_post_id,
                clue_index=None,
                required=True,
                source=source,
                excerpt=excerpt,
            )
            cited = ProfileEvidence(
                required=True,
                source="open_data",
                excerpt=_corporation_excerpt(written, name, gazetteer),
            )
            for supporting in _supporting_groups(posts, anchor_post_id, written):
                refs = [
                    ProfileEvidence(
                        post_id=p.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=written,
                    )
                    for p in supporting
                ]
                candidates.setdefault(name, []).append(
                    ProfileEvidencePath(
                        evidence=[anchor_ref, *refs, cited], confidence=EMPLOYER_CONFIDENCE
                    )
                )
    if len(candidates) != 1:
        return None
    value, paths = next(iter(candidates.items()))
    return ProfileItem(
        attribute=ProfileAttribute.EMPLOYER_NAME,
        value=value,
        confidence=EMPLOYER_CONFIDENCE,
        status=ProfileStatus.WEAK,
        evidence=[ref for path in paths for ref in path.evidence],
        evidence_paths=paths,
        assessment=ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY),
    )


def _employer_names(text: str, gazetteer: Gazetteer) -> list[tuple[str, str]]:
    """(抜き出した文, 書かれた名前)。表で引ける、いちばん長い書き方を名前にする。"""
    found: list[tuple[str, str]] = []
    for match in EMPLOYER_PREFIX_RE.finditer(text):
        tail = match.group("tail")[:MAX_EMPLOYER_NAME_LENGTH]
        written = _longest_known([tail[:end] for end in range(len(tail), 1, -1)], gazetteer)
        if written and not _third_party(text, match.start()):
            found.append((match.group(0), written))
    for match in EMPLOYER_SUFFIX_RE.finditer(text):
        head = SENTENCE_START_RE.split(text[: match.start()])[-1][-MAX_EMPLOYER_NAME_LENGTH:]
        written = _longest_known([head[start:] for start in range(len(head) - 1)], gazetteer)
        if written and not _third_party(text, match.start()):
            found.append((written + match.group(0), written))
    return found


def _longest_known(spellings: list[str], gazetteer: Gazetteer) -> str:
    """長い順に試し、表に1件以上ある最初の書き方。なければ空。"""
    return next((s for s in spellings if gazetteer.corporations_named(s)), "")


def _third_party(text: str, position: int) -> bool:
    sentence = re.split(r"[。！？!?\n]", text[:position])[-1]
    return bool(THIRD_PARTY_SUBJECT_RE.search(sentence))


def _supporting_groups(
    posts: Sequence[Post], anchor_post_id: str | None, written: str
) -> list[list[Post]]:
    """名前が書かれた別の投稿。プロフィール文が関係を示すときは、投稿が2件要る。"""
    others = [
        p
        for p in posts
        if p.post_id != anchor_post_id and written in p.text and not forbidden_context(p.text)
    ]
    if anchor_post_id is not None:
        return [[p] for p in others]
    return [others[:2]] if len(others) >= 2 else []


def _corporation_excerpt(written: str, legal_name: str, gazetteer: Gazetteer) -> str:
    as_of = gazetteer.corporations_as_of()
    when = ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        year, month, day = (int(part) for part in as_of.split("-"))
        when = f"。{year}年{month}月{day}日時点"
    return f"{written}の正式名称は{legal_name}（{CORPORATION_CITATION}{when}）"
