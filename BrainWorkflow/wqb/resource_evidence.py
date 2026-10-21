"""Pure source-premise verification; shape/version flags never grant authority.

Callers supply complete UTF-8 source text (or original bytes), not previews.
Markdown content_hash binds the LF-normalized body when front matter exists;
file_sha256 binds the original full bytes. JSON/JSONL content_hash binds full
bytes. These are the existing semantic compiler/index conventions. This module
resolves the explicit regular Delay-1 timing rule and three finite typed
operator rules. Paired version agreement belongs to Task4's consumer.

Markdown locators support canonical ATX headings, simple fences and same-line
inline code, not full CommonMark. With comment markers anywhere in the body,
escaped backticks/comment openers and unmatched/multiline inline-code runs
outside fences fail explicitly as unsupported Markdown. This conservative
boundary prevents ambiguous syntax from exposing hidden comment facts.
"""

import ast
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import html
import json
from pathlib import PurePosixPath
import re
import unicodedata

from wqb.knowledge_contracts import parse_markdown_front_matter
from wqb.knowledge_age_policy import KNOWLEDGE_MAX_AGE_DAYS
from wqb.semantic_contracts import (
    MAX_JSON_DEPTH, MAX_PREMISES, MAX_QUOTE_BYTES, _indexed_source, premise_from_dict,
    resource_scope_from_dict, timing_contract_from_dict, validate_semantic_record,
    definition_basis_from_dict, operator_definition_from_dict, evidence_ref_from_dict,
)


SOURCE_FAMILIES = {
    "platform_learn_material": {"raw/platform/learn"},
    "platform_data_field_capture": {"raw/platform/data_fields"},
    "platform_activity_snapshot": {"raw/platform/activities"},
}
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
JSON_ROW_KEYS = {"rows", "results", "data_fields"}
HEADER_KEY_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.*)\Z")
REGULAR_DELAY_POLICY = (
    "In this case, there is a lag of 1 day. This is called Delay 1 simulation. "
    "In expression language, delay is applied automatically and you do not have to bother about it."
)
TIMING_CLASSIFICATION_COLUMNS = ["Dataset", "Field", "Instrument type", "Region", "Delay", "Universe", "Cutoff class", "Timing policy"]
NAMED_REGULAR_COMPARISON = (
    r"Regular D1 Field: (?P<regular>[A-Za-z_][A-Za-z0-9_]*) "
    r"Fast D1 Field: (?P<fast>[A-Za-z_][A-Za-z0-9_]*)"
)
NAMED_CUTOFF_COMPARISON = (
    r"Delay Field Type Data Timestamp Information Captured 1 (?P<regular>[A-Za-z_][A-Za-z0-9_]*) "
    r"Yesterday['\u2019]s market close Yesterday['\u2019]s End-of-day data only "
    r"Fast D1 (?P<fast>[A-Za-z_][A-Za-z0-9_]*) Today['\u2019]s market open "
    r"Overnight news, events, pre-market moves"
)
REGULAR_DELAY_RULE = dict(
    rule_id="regular_delay_1", rule_version=3, cutoff_class="regular_delay_1",
    policy=REGULAR_DELAY_POLICY, policy_heading="How to choose the Simulation Settings",
    classification_columns=TIMING_CLASSIFICATION_COLUMNS, classification_rows=1,
    classification_cutoff="Regular Delay 1", classification_policy="Expression language automatic delay",
    classification_formats=["single_row_table", "explicit_key_values", "named_regular_and_cutoff_comparison"],
    comparison_heading="Fast D1 Documentation", naming_pattern=NAMED_REGULAR_COMPARISON,
    cutoff_pattern=NAMED_CUTOFF_COMPARISON, comparison_suffix="_fast_d1",
    cutoff_labels=["regular delay 1", "regular d1", "regular_delay_1"],
    policy_labels=["expression language automatic delay", "expression-language automatic delay"],
    capture_value_path=[], capture_endpoint="/data-fields", field_types=["MATRIX", "GROUP"],
    source_scope_keys=["instrument_type", "region", "delay", "universe"],
    max_source_age_days=KNOWLEDGE_MAX_AGE_DAYS,
)
OPERATOR_RULES = {
    "ts_delta": dict(rule_id="ts_delta", rule_version=1, names=["x", "d"],
                     types=["MATRIX", "INTEGER"], input_types=["MATRIX"], output_type="MATRIX",
                     meaning="Calculates the difference between a value and its delayed version over a specified period."),
    "group_rank": dict(rule_id="group_rank", rule_version=1, names=["x", "group"],
                       types=["MATRIX", "GROUP"], input_types=["MATRIX", "GROUP"], output_type="MATRIX",
                       meaning="Ranks each element within its group based on the input field, assigning a value between 0.0 and 1.0."),
    "group_neutralize": dict(rule_id="group_neutralize", rule_version=1, names=["x", "group"],
                             types=["MATRIX", "GROUP"], input_types=["MATRIX", "GROUP"], output_type="MATRIX",
                             meaning="Neutralizes Alpha values within each specified group by subtracting the group mean from each value."),
}
PROJECT_WINDOW_POLICY = dict(
    owner="project", operator="ts_delta", parameter="d", type="INTEGER",
    minimum=1, maximum=2520, default_horizons=[5, 22, 122, 252],
    platform_domain_complete=False, selection="one_justified_horizon_not_a_grid",
    source_restrictions="explicit_contrary_constraints_reject",
)
OPERATOR_RULES["ts_delta_project_window"] = dict(
    OPERATOR_RULES["ts_delta"], rule_id="ts_delta_project_window", rule_version=2)
OPERATOR_MEANING_SUFFIXES = {
    "ts_delta": " Useful for measuring changes or momentum in time-series data.",
    "group_rank": " This helps compare items within the same group, such as stocks in the same industry.",
    "group_neutralize": " Groups can be industry, sector, country, or any custom grouping.",
}
MATRIX_FACTS = (
    "This is unlike regular matrix data that you work with, which has one value per day per instrument.",
    "Now, whenever you write an Alpha expression, the end result is a matrix of Alpha values which is the position that is taken in the market.",
    "And all the operators on platform are made for matrix input, hence use the matrix operator only after using the vec_ operators to convert the vector data field to matrix field.",
)
GROUP_FACT = (
    "Group Data Fields are fields which have information about instrument segregation into various groups. "
    "They are supposed to be used as an input to the group operator."
)
INTEGER_WINDOW_PATTERN = re.compile(
    r"For Fast Expression ts_delta\(x, d\), d must be a (?:positive|non-negative) integer number of days\."
)
OPERATOR_DOCUMENT_HEADINGS = {
    "matrix": "Vector Data Fields", "group": "Group Data Fields",
}
# Full normalized July 09 sections, including Page id/Category. Unknown extra
# clauses must be reviewed as a new finite context, not accepted by substring.
OPERATOR_TYPE_SECTION_HASHES = {
    "matrix": {"0ec33c9ed5527a0c23ff8b9a61e149bf81bfceec9e9b2f866993c06ba6982de1"},
    "group": {"c43b7964375e7f5f1b64eee314616225940a967834c0295e0bca50158bb07684"},
}
OPERATOR_TYPE_ANCESTORS = {"Documentation Pages", "Fast Expression", "REGULAR Fast Expression"}
OPERATOR_CONTAINER_INTRO = re.compile(r"(?:Record count: [0-9]+)?")
OPERATOR_WINDOW_HEADING = re.compile(r"(?:Fast Expression time-series parameters|Time-series (?:operator reference|parameters))")
OPERATOR_WINDOW_CANDIDATE = re.compile(r"\b(?:ts_delta|windows?|lookback|time.series|parameters?|constraints?)\b", re.IGNORECASE)
OPERATOR_WINDOW_SUBJECT = re.compile(r"\b(?:ts_delta|d|windows?|lookback)\b", re.IGNORECASE)
OPERATOR_WINDOW_RELATION = re.compile(r"\bts_delta\b|\bd\b[^\n.]*\b(?:must|integer|days?|window|lookback|greater|less|positive|even|odd)\b", re.IGNORECASE)
OPERATOR_CAPTURE_LINE = re.compile(
    r"(?:- (?:Source id|Scope|Level|Documentation|Definition|Description|Input types|Output type): .+"
    r"|- Parameters:|  - `[A-Za-z_][A-Za-z0-9_]*`: type=`[A-Z]+`, required=`(?:true|false)`(?:, default=`[^`]+`)?)"
)
OPERATOR_CONTEXT_POLICY_VERSION = 5
DELTA_PAGE_MEANING = 'The ts_delta(x, d) operator computes the difference between the current value of x and its value d periods ago.'
DELTA_PAGE_INTRO = DELTA_PAGE_MEANING + ' This is a simple way to measure how much a variable has changed over a given time window, making it useful for detecting trends, momentum, or reversals in time-series data. Example calculations Suppose you have a time series of daily closing prices for a stock:'
DELTA_PAGE_ILLUSTRATION = 'If you want to calculate the 3-day delta for Day 5: ts_delta(price, 3) on Day 5 = price on Day 5 - price on Day 3 = 108 - 105 = 3 Examples ts_delta(close, 5) What to expect: Today\u2019s close minus the close five days ago; positive for 5\u2011day up moves, negative for down moves.'
MATRIX_PAGE_CONTEXT = (
    'Vector Data are a distinct type of data fields that do not have a fixed size. In such type of data fields, '
    'the number of events recorded per day per instrument varies, so they are typically stored in a vector. '
    + MATRIX_FACTS[0] + ' For example: If a dataset covers news data, it could be a vector because for each instrument '
    'there can be different number of news/events happening hence, covering such information in a matrix data tends '
    'to result in missing useful information. For example, a vector field reporting multiple news events for a single '
    'instrument in a day. ' + MATRIX_FACTS[1] + ' ' + MATRIX_FACTS[2] + ' This is done by aggregating vector for each day '
    'and instrument into a single value like a matrix has. The same is depicted in figure below:'
)
DOCUMENTATION_PAGE_POLICY = dict(
    version=5, page_keys=['id', 'title', 'category', 'sequence', 'lastModified', 'content'],
    parameter_guard_pages=['ts_delta', 'vector-datafields', 'group-data-fields'],
    optional_page_keys=['duration'], duration_pattern=r'PT[1-9][0-9]*M',
    endpoints={'operator_detail': '/operators/{id}', 'tutorial': '/tutorial-pages/{id}'},
    block_types=['TEXT', 'EQUATION', 'HEADING', 'TABLE', 'IMAGE', 'SIMULATION_EXAMPLE'],
    compiled_targets=['wiki/00_start_here.md', 'wiki/10_factor_principles.md', 'wiki/20_data_semantics.md',
                      'wiki/30_template_and_operator_patterns.md', 'wiki/40_benchmark_and_repair_rules.md'],
    titles={'ts_delta': ['ts_delta'], 'vector-datafields': ['Vector Data Fields', 'Vector Data Fields \U0001f949'],
            'simulation-settings': ['How to choose the Simulation Settings'],
            'fast-d1-documentation': ['Fast D1 Documentation'],
            'group-data-fields': ['Group Data Fields', 'Group Data Fields \U0001f948']},
    categories={'ts_delta': 'Operators', 'vector-datafields': 'Data', 'simulation-settings': 'Getting Started',
                'fast-d1-documentation': 'Advanced Topics', 'group-data-fields': 'Data'},
    duplicate_payload='required_for_material_kind_documentation_page_legacy_absent_only',
    context_headings=['Delay', 'What is Fast D1?', 'How Fast D1 Works', 'How to Simulate Fast D1 Alphas'],
)
PAGE_RELEVANT_CLAUSE = re.compile(
    r'\b(?:matrix|ts_delta|input|output|must|cannot|except|constraint|integer|periods|lookback|'
    r'delay|cutoff|snt_buzz|available|availability|regular|fast.d1|'
    r'positive|negative|zero|even|odd|default|permit|permitted|require|required|restriction|'
    r'operators?|function|accepts?|vector|only|never|not|invalid|unsupported|'
    r'minimum|maximum|bounds?|range)\b', re.IGNORECASE)
PAGE_NUMERIC_RESTRICTION = re.compile(
    r'\b[A-Za-z_][A-Za-z0-9_]*\s*(?:[<>!=]=?|\u2264|\u2265)\s*[-+]?\d'
    r'|(?<![\w.])[-+]?\d+(?:\.\d+)?\s*(?:[<>!=]=?|\u2264|\u2265)\s*[A-Za-z_]'
    r'|\b(?:d|window|lookback)\b\s*(?:in|\u2208)\s*[\[{]\s*[-+]?\d', re.IGNORECASE)
PAGE_WINDOW_PARAMETER = re.compile(r'(?<!\w)(?:d|windows?|lookbacks?|look[- ]backs?)(?=\W|_|$)', re.IGNORECASE)
PAGE_PARAMETER_SUBSCRIPT = re.compile(r'[\u2080-\u209f]')
PAGE_MATH_CONSTRAINT_MARKER = re.compile(
    r'[<>=!+*/%^\-\u2264\u2265\u2260\u2208\u2209]'
    r'|\\(?:geq?|leq?|neq?|lt|gt|in|notin|equiv|subseteq?|supseteq?)\b', re.IGNORECASE)
PAGE_SEMANTIC_HTML = re.compile(
    r'<\s*/?\s*(?:del|s|strike|script|template|noscript)\b'
    r'|<[^>]*\s(?:hidden|inert)(?:\s|=|/?>)'
    r'|<[^>]*\saria-hidden\s*=\s*["\']?true\b'
    r'|display\s*:\s*none\b|visibility\s*:\s*(?:hidden|collapse)\b'
    r'|text-decoration(?:-line)?\s*:[^;"\']*\bline-through\b', re.IGNORECASE)
# Audited ancillary blocks are not meaning/type proofs. Explicit operation and
# MATRIX passages below remain mandatory; new relevant clauses fail closed.
PAGE_ANCILLARY_DIGESTS = {
    'vector-datafields': ['53ddbf6c0736b94796157a3e0e36fea6e0918ee4ca4206a1dba6e422a722dcfa',
                          '2d99769dcc8d32eceed55421450a94430c7013bad09dc26dde8476c3e48ecd17',
                          'e7bc31003aa880f94d50cf763d1a48d5ab20a02b7c4fb65b72f3ecc7b723179e'],
    'simulation-settings': [
        '81022118c1381048794c3207aaaa140c2fbb5d935ce1b0f4dc785834e04b2021',
        '353aadfaa6a354c9df4fc7ffa3904170e4d87205995f5279622cae2ee7e639ee',
        '1d4311d30c2166360c18abf5789c2aea26c1f6c334f26c5c6867cf3b1fde3330',
        'f4fb57bcdf5d4a811f433760d04386eefe3d6e47357246510cc54dc0771be6a1',
        '5ca7f21acdbe63e8594c84daf8990e8d1d81ffb84b12929de2af38f1862c7d04',
        'fefbd2cc22624c9661b622bd2b794b06781a70a76c04dd24704fd025041416df',
        '348bc75eb5fe78305483a00fdf7bbb22904b5dc8223783e3b9862dbe465ea759',
        'a8821d3c59b726b1c7e8dd09692ecb3e9a5ae40209396c763bead1f613b141d6',
        'c907c6ad98896d601d92571b9346ed9157be2799fd1d32324b3e11c564d4f4ef',
        'a6fcb2e47c8f97d04a694578dfc1a17f949979a4e3f0bf2432ad17cd09ac91d6',
        '4ff4fa8c7d802bd0479e6bd13dab6077cae2eb42e7b5ba9ff78bd0b9032be9a7',
        '0fa99d8090542360a74fd1ab7db79a7709a225b15df26a9a59a8843cfe63df4d',
        '60eea60db6ec7a596fce85e179b6f3e136e2277e6f17888be3802402f93a54b2',
        'c8b8a011a9e5a776edd8f32b678e2f318c7c35d75ff302685d894d6071f0d9fb',
        '1258227cbb63a30f5cce87a8f0ccdadee544591159e0cae5cabdd6815b4081cd',
        'e81c98b4633e47e54ab91335dda288b7ea7726b7fbaf9d076d117c51a3d07753',
        '3990f9db93fa89f9837c557c77647bffa7fc9fa15a298425203f14bd5b7c3c00',
        '48002929c1a517c3024f4c570f57d1579d2f507955ef27fbd064eb60881cc758',
        '800ba2b0af25a8fc79bb1f57db5532b4c46a839fe1b7d2ba787a16ec9f9ab559',
        'dd47ee27400c7c02d1ac44ae1c418572555dae9188189bfaf8aa557e99d8a7e3',
        'c4c859d31d46130a2a67b43a41a7453c946dadedd68253802014635cc7ada9a1',
        '69cffac7d793d750d87c0b790ae2adc3f46820dde2712814f6ad2b01fafc74bd'],
    'fast-d1-documentation': [
        '154cac7e62d773b0270902c3daa5cc16fe060410b87255822a506f6da177e4d5',
        '5625bee20b7c409c4b07aaefa3b76eb8d586c7f5b23ddd4bbd49cc344ca8d591',
        '88f2e644b5fe7854afeb6c772119e2fda2e0a41a6af26809779901b2e14b8fd5',
        '85e57398e1415dfc20a08a9820fee1dfa6143d79dacbb68beee4fcdfb83904ce',
        'c157494d8fc8778202318c3ea4fef1825b355c0502128a161d4fadd8f8804790',
        '5bfcf9082fa5ffb8858eed59e0362bfa6b4524bbc85d6d01cf4abdc2150d1c41',
        '5746308df2518dd36b9faa3df76f3f9dfb52088d0fc3ec2326d9bdad3e1acd3e',
        'b18ceb635ce594ba1d1f20820ed604be3ce0e7b21f09e778cf1ce913c950793c',
        'd476d221c8fa5e064b1ad1ccefb8600de9475f058ceff86a78956a097d20a71b',
        '097d1003bc45c0e1f8aca14b3463f56fae80dc587ffe5deb15e0d6633e6fe877',
        'cca896f489e849a5c374e8b22c1fcbf4b03711e86bb2d8b7f3025d10c51ed60f',
        '810b5480148ac39cc7c5ce844299bf0a66e03fff10f8429f5e428265e8ac535c',
        '289345039824e5536b03a3700c9661c07015912a936e5cb09401ef247b29462c',
        'f868801ba08ba4c53d60e1d872b2ef96deb768bd7ecf72f4336d109b90d9365b'],
}
OPERATOR_RECEIPT_POLICY = dict(
    version=1, heading="Raw GET Receipt", keys=["generated_at", "target", "endpoint", "payload", "error"],
    row_keys=["name", "category", "scope", "level", "documentation", "definition", "description"],
    envelope_keys=["results", "count", "next", "previous"],
    endpoints={"operators": "/operators", "operator": "/operators", "operator_detail": "/operators/{id}"},
    capture_tool="scripts/capture_learn_material.py", content_status="raw_markdown",
    header_keys=["source_type", "source_family", "source_path", "captured_at", "capture_tool", "content_status",
                 "record_count", "content_hash", "payload_hash", "update_check", "compiled_targets", "path", "file_sha256"],
    update_check="compare record count, content hash, and platform endpoint against the previous Learn capture",
    compiled_targets=["wiki/30_template_and_operator_patterns.md", "machine/operator_ledger.jsonl"],
    body_format="complete_canonical_operator_cards_then_one_terminal_json_receipt",
)


def resource_contract_version(envelope: dict) -> int:
    """Input: dict. Output: int (1/2). Parse opt-in; absent is legacy, bool is invalid."""
    if not isinstance(envelope, dict):
        raise ValueError("expected resource envelope object")
    version = envelope.get("resource_contract_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported resource contract version")
    return version


def _equal(left: object, right: object) -> bool:
    """Input: two JSON objects. Output: bool. Compare exact recursive types, including bool/int."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def _check_header(text: str) -> None:
    """Input: LF Markdown str. Output: None. Prevalidate flat header structure before legacy parsing."""
    if not text.startswith("---\n"):
        return
    seen = set()
    list_allowed = False
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            return
        if not line.strip():
            continue
        if line.startswith("  - "):
            if not list_allowed:
                raise ValueError("frontmatter list requires an empty-valued key")
            continue
        match = HEADER_KEY_RE.fullmatch(line)
        if not match:
            raise ValueError("unsupported frontmatter structure")
        key, value = match.groups()
        if key in seen:
            raise ValueError("duplicate frontmatter key: " + key)
        seen.add(key)
        list_allowed = not value.strip()
    raise ValueError("unterminated frontmatter header")


def _source(ref: dict, source_index: dict, source_texts: dict) -> str:
    """Input: ref/index/full sources dicts. Output: verified body str. Check identity and actual bytes."""
    if not isinstance(source_index, dict) or not isinstance(source_texts, dict):
        raise ValueError("expected source index and complete source texts")
    path = ref["source_path"]
    row = _indexed_source(path, source_index)
    if "source_path" in row and row["source_path"] != path:
        raise ValueError("indexed source identity mismatch")
    issues = validate_semantic_record(dict(evidence_refs=[ref]), source_index)
    if issues:
        raise ValueError("invalid premise provenance: " + issues[0]["message"])
    if row["source_family"] not in SOURCE_FAMILIES.get(row["source_type"], set()):
        raise ValueError("unsupported official source family")
    supplied = source_texts.get(path)
    if not isinstance(supplied, (str, bytes)):
        raise ValueError("missing complete source bytes/text")
    raw = supplied.encode("utf-8") if isinstance(supplied, str) else supplied
    text = raw.decode("utf-8")
    full_hash = hashlib.sha256(raw).hexdigest()
    if "file_sha256" in row and (not isinstance(row["file_sha256"], str) or row["file_sha256"].lower() != full_hash):
        raise ValueError("source full-file hash mismatch")
    content = raw
    body = text
    if PurePosixPath(path).suffix.lower() == ".md":
        normalized = text.replace("\r\n", "\n")
        _check_header(normalized)
        metadata, body = parse_markdown_front_matter(normalized)
        if metadata:
            content = body.encode("utf-8")
            for key in ("content_hash", "captured_at", "source_type", "source_family"):
                if key in metadata and not _equal(metadata[key], row[key]):
                    raise ValueError("frontmatter/index mismatch: " + key)
            for key in ("source_path", "path"):
                if key in metadata and metadata[key] != path:
                    raise ValueError("frontmatter source identity mismatch")
            if "scope" in metadata and "scope" in row and not _equal(metadata["scope"], row["scope"]):
                raise ValueError("frontmatter/index scope mismatch")
            if "file_sha256" in metadata and metadata["file_sha256"] != full_hash:
                raise ValueError("frontmatter full-file hash mismatch")
    if hashlib.sha256(content).hexdigest() != row["content_hash"].lower():
        raise ValueError("source content hash mismatch")
    return body


def _comment_mask(body: str) -> list[bool]:
    """Input: Markdown str. Output: list[bool]. Mask comments; reject ambiguous escaped/multiline code."""
    hidden = [False] * len(body)
    comment = False
    fence = None
    offset = 0
    has_comment_markers = "<!--" in body or "-->" in body
    for line in body.splitlines(keepends=True):
        marker = FENCE_RE.match(line) if not comment else None
        if fence is not None:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif marker:
            fence = marker[1]
        else:
            if has_comment_markers and re.search(r"\\(?:`|<!--)", line):
                raise ValueError("unsupported Markdown: escaped backtick/comment opener with comment markers")
            pos = 0
            inline_ticks = 0
            while pos < len(line):
                if comment:
                    end = line.find("-->", pos)
                    stop = len(line) if end == -1 else end + 3
                    hidden[offset + pos:offset + stop] = [True] * (stop - pos)
                    comment = end == -1
                    pos = stop
                elif line[pos] == "`":
                    stop = pos + 1
                    while stop < len(line) and line[stop] == "`":
                        stop += 1
                    count = stop - pos
                    if not inline_ticks:
                        # An unmatched backtick is literal text, not a code span.
                        closer = re.search(r"(?<!`)`{" + str(count) + r"}(?!`)", line[stop:])
                        if closer:
                            inline_ticks = count
                        elif has_comment_markers:
                            raise ValueError("unsupported Markdown: unmatched or multiline inline code with comment markers")
                    elif count == inline_ticks:
                        inline_ticks = 0
                    pos = stop
                elif not inline_ticks and line.startswith("<!--", pos):
                    comment = True
                else:
                    pos += 1
        offset += len(line)
    return hidden


def _markdown_value(body: str, locator: dict) -> str:
    """Input: verified Markdown/locator dict. Output: str. Locate exact LF quote under a unique heading."""
    headings = []
    hidden = _comment_mask(body)
    fence = None
    offset = 0
    for original in body.splitlines(keepends=True):
        line = "".join("\0" if hidden[offset + i] and char != "\n" else char for i, char in enumerate(original))
        marker = FENCE_RE.match(line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif fence is None:
            match = HEADING_RE.match(line.rstrip("\n"))
            if match and "\0" not in line:
                title = re.sub(r"[ \t]+#+$", "", match[2])
                headings.append((title, len(match[1]), offset, offset + len(line)))
        offset += len(line)
    matches = [item for item in headings if item[0] == locator["heading"]]
    if len(matches) != 1:
        raise ValueError("Markdown heading missing or duplicated")
    _, level, start, content_start = matches[0]
    end = next((pos for _, depth, pos, _ in headings if pos > start and depth <= level), len(body))
    quote = locator["quote"].replace("\r\n", "\n")
    occurrences = []
    pos = body.find(quote, content_start, end)
    while pos != -1:
        if not any(hidden[pos:pos + len(quote)]):
            occurrences.append(pos)
        pos = body.find(quote, pos + len(quote), end)
    if len(occurrences) != 1:
        raise ValueError("exact quote missing or ambiguous within heading section")
    return quote


def _json_object(pairs: list[tuple]) -> dict:
    """Input: parsed JSON pairs list. Output: dict. Reject duplicate keys rather than overwrite facts."""
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError("duplicate JSON key")
        row[key] = value
    return row


def _invalid_constant(value: str) -> None:
    """Input: non-JSON constant str. Output: raises ValueError. Reject NaN/Infinity source facts."""
    raise ValueError("nonfinite JSON constant: " + value)


def _check_scoped_facts(value: object, scope: dict, depth: int = 0) -> None:
    """Input: captured JSON object, exact scope dict, depth int. Output: None or ValueError. Reject conflicting scoped facts."""
    if depth > MAX_JSON_DEPTH:
        raise ValueError("captured scope nesting exceeds bound")
    if isinstance(value, dict):
        for key, fact in value.items():
            if key in scope and not _equal(fact, scope[key]):
                raise ValueError("captured nested scope/type conflict: " + key)
            if key in ("scope", "sourceScope") and not _equal(resource_scope_from_dict(fact), scope):
                raise ValueError("captured nested scope object conflict")
            _check_scoped_facts(fact, scope, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_scoped_facts(item, scope, depth + 1)


def _json_value(body: str, locator: dict, suffix: str, source: dict) -> object:
    """Input: verified JSON/body locator/suffix/index row. Output: JSON value. Require unique scoped row."""
    def parse(text: str) -> object:
        """Input: JSON str. Output: JSON object. Parse without duplicate-key or numeric coercion."""
        return json.loads(text, object_pairs_hook=_json_object, parse_constant=_invalid_constant)

    if suffix == ".jsonl":
        rows = [parse(line) for line in body.splitlines() if line.strip()]
    else:
        payload = parse(body)
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict) and {"data_set", "field"} <= payload.keys() and ("scope" in payload or "sourceScope" in payload):
            rows = [payload]
        elif isinstance(payload, dict) and {"dataset_id", "field_id"} <= payload.keys() and ("scope" in payload or "sourceScope" in payload):
            rows = [payload]
        elif isinstance(payload, dict) and len(JSON_ROW_KEYS & payload.keys()) == 1:
            rows = payload[next(iter(JSON_ROW_KEYS & payload.keys()))]
        else:
            raise ValueError("unsupported JSON row container")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("expected JSON source rows")
    identity = locator["row_identity"]
    if "scope" in source and not _equal(source["scope"], identity["scope"]):
        raise ValueError("indexed scope mismatches premise identity")
    matches = []
    for row in rows:
        actual = {key: row.get(key) for key in ("dataset_id", "field_id", "scope")}
        if "sourceScope" in row:
            captured_scope = resource_scope_from_dict(row["sourceScope"])
            if "scope" in row and not _equal(row["scope"], captured_scope):
                raise ValueError("conflicting captured scope alias")
            actual["scope"] = captured_scope
        for key in ("capturedAt", "generated_at"):
            if key in row and _timestamp(row[key]) != _timestamp(source["captured_at"]):
                raise ValueError(key + "/index capture time mismatch")
        for alias, key in (("data_set", "dataset_id"), ("field", "field_id")):
            if alias not in row:
                continue
            nested = row[alias]
            if not isinstance(nested, dict) or type(nested.get("id")) is not str or not nested["id"].strip():
                raise ValueError("invalid captured identity alias: " + alias)
            if key in row and not _equal(row[key], nested["id"]):
                raise ValueError("conflicting identity alias: " + key)
            actual[key] = nested["id"]
        if "field" in row and "dataset" in row["field"]:
            dataset = row["field"]["dataset"]
            if not isinstance(dataset, dict) or type(dataset.get("id")) is not str or not dataset["id"].strip():
                raise ValueError("invalid captured identity alias: field.dataset")
            if not _equal(dataset["id"], actual["dataset_id"]):
                raise ValueError("conflicting identity alias: field.dataset")
        if _equal(actual, identity):
            resource_scope_from_dict(actual["scope"])
            _check_scoped_facts(row, identity["scope"])
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("JSON row identity missing or duplicated")
    value = matches[0]
    for key in locator["value_path"]:
        if not isinstance(value, dict) or key not in value:
            raise ValueError("JSON value path missing; only literal object keys allowed")
        value = value[key]
    if not _equal(value, locator["expected_value"]):
        raise ValueError("JSON value/type mismatch")
    return deepcopy(value)


def _markdown_field_capture(body: str, source: dict, text: str | bytes) -> str:
    """Input: verified body/index/full text. Output: canonical captured JSON, not original-receipt verification.

    IO producers must verify the extraction receipt against the original before
    supplying this source pack; this pure adapter never grants trust from a marker.
    """
    path = source['path']
    match = re.fullmatch(r'raw/platform/data_fields/([0-9]{4}-[0-9]{2}-[0-9]{2})/semantic-subset-([a-f0-9]{64})\.md', path)
    if (not match or source.get('source_type') != 'platform_data_field_capture'
            or source.get('source_family') != 'raw/platform/data_fields'
            or source.get('content_status') != 'verified_raw_extract'):
        raise ValueError('JSON Markdown requires a canonical field capture excerpt')
    text = text.decode('utf-8') if isinstance(text, bytes) else text
    metadata, _ = parse_markdown_front_matter(text.replace('\r\n', '\n'))
    if (metadata.get('content_status') != 'verified_raw_extract'
            or metadata.get('capture_tool') != 'knowledge_contracts.extract_field_source_subset'
            or metadata.get('original_source_path') != f'raw/platform/data_fields/{match[1]}/data_fields.jsonl'
            or metadata.get('extraction_receipt') != f'machine/semantic_jobs/{match[2]}/field_source_extract.json'
            or not isinstance(metadata.get('original_sha256'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', metadata['original_sha256'])):
        raise ValueError('field capture extraction provenance is missing or inconsistent')
    block = re.fullmatch(r'# Verified Field Source Extract\n\n```json\n(.*)\n```\n', body, re.DOTALL)
    if not block:
        raise ValueError('unsupported field capture Markdown container')
    payload = json.loads(block[1], object_pairs_hook=_json_object, parse_constant=_invalid_constant)
    if not isinstance(payload, dict) or set(payload) != {'rows'} or not isinstance(payload['rows'], list):
        raise ValueError('field capture requires exact rows container')
    return block[1]


def verify_premise(premise: dict, source_index: dict, source_texts: dict) -> object:
    """Input: premise/index/complete sources dicts. Output: located str/JSON value, or ValueError.

    Verify provenance and complete content before looking up exact locator facts.
    Returned facts carry no derived timing/type or lifecycle authority.
    """
    parsed = premise_from_dict(premise)
    ref, locator = parsed["evidence_ref"], parsed["locator"]
    body = _source(ref, source_index, source_texts)
    suffix = PurePosixPath(ref["source_path"]).suffix.lower()
    if locator["kind"] == "markdown_quote" and suffix == ".md":
        _documentation_page(body, source_index[ref['source_path']], source_texts[ref['source_path']])
        return _markdown_value(body, locator)
    if locator["kind"] == "json_value" and suffix in (".json", ".jsonl"):
        return _json_value(body, locator, suffix, source_index[ref["source_path"]])
    if locator['kind'] == 'json_value' and suffix == '.md':
        source = source_index[ref['source_path']]
        payload = _markdown_field_capture(body, source, source_texts[ref['source_path']])
        return _json_value(payload, locator, '.json', source)
    raise ValueError("locator/source format mismatch")


def _timestamp(value: object) -> datetime:
    """Input: ISO timestamp object. Output: aware datetime or ValueError. Never consult the clock."""
    if not isinstance(value, str):
        raise ValueError("expected explicit timezone-aware timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expected explicit timezone-aware timestamp")
    return parsed


def _digest(value: object) -> str:
    """Input: finite JSON value. Output: SHA256 str. Bind deterministic rule/contract/receipt bytes."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _operator_signature(quote: str, operator: str, rule: dict) -> tuple[list, str]:
    """Input: verified operator block/name/rule. Output: parameter dict list and description str. Parse syntax, never types."""
    if any(line.strip() and not OPERATOR_CAPTURE_LINE.fullmatch(line) for line in quote.splitlines()):
        raise ValueError("unsupported operator capture clause or exception")
    labels = {}
    for label in ("Source id", "Scope", "Definition", "Description"):
        values = re.findall(r"^- " + label + r": (.+)$", quote, re.MULTILINE)
        if len(values) != 1:
            raise ValueError("signature premise needs one captured " + label)
        labels[label] = values[0]
    if labels["Source id"] != "`" + operator + "`":
        raise ValueError("signature operator identity mismatch")
    scopes = ast.literal_eval(labels["Scope"])
    if (not isinstance(scopes, list) or any(type(item) is not str for item in scopes)
            or len(scopes) != len(set(scopes)) or "REGULAR" not in scopes):
        raise ValueError("operator signature is not applicable to REGULAR Fast Expression")
    signature = labels["Definition"]
    if not re.fullmatch(r"`[^`]+`", signature):
        raise ValueError("expected captured expression signature")
    call = ast.parse(signature[1:-1], mode="eval").body
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != operator:
        raise ValueError("expected exact operator call signature")
    parameters = []
    for argument in call.args:
        if not isinstance(argument, ast.Name):
            raise ValueError("signature positional argument must be a parameter name")
        parameters.append(dict(name=argument.id, required=True))
    for keyword in call.keywords:
        if keyword.arg is None or not isinstance(keyword.value, ast.Constant) or type(keyword.value.value) not in (str, int, float, bool):
            raise ValueError("signature defaults must be literal scalar values")
        parameters.append(dict(name=keyword.arg, required=False, default=keyword.value.value))
    if [parameter["name"] for parameter in parameters] != rule["names"]:
        raise ValueError("unsupported operator parameter names/order")
    return parameters, labels["Description"]


def _operator_capture(body: str, operator: str) -> str | None:
    """Input: verified Markdown body/operator str. Output: complete captured section str or None. Reject ambiguous hidden facts."""
    headings = list(re.finditer(r"^#{1,3}[ \t]+([^\n]+)$", body, re.MULTILINE))
    matches = [i for i, heading in enumerate(headings) if heading[1].strip().strip("`") == operator]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("duplicate operator capture identity")
    number = matches[0]
    section = body[headings[number].end():headings[number + 1].start() if number + 1 < len(headings) else len(body)]
    if any(token in section for token in ("<!--", "-->", "```", "~~~")):
        raise ValueError("unsupported hidden/fenced operator capture")
    return section


def _operator_premise_section(body: str, locator: dict, allowed_ancestors: set[str]) -> str:
    """Input: verified Markdown/locator/finite ancestor names. Output: normalized full section str or ValueError.

    Match the premise verifier's visible ATX/fence boundary. Validate the whole
    containing section and every ancestor's direct introduction, never only a
    favourable quote. Unknown container prose or language scope fails closed.
    """
    headings, fence, offset = [], None, 0
    hidden = _comment_mask(body)
    for original in body.splitlines(keepends=True):
        line = "".join("\0" if hidden[offset + i] and char != "\n" else char for i, char in enumerate(original))
        marker = FENCE_RE.match(line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif fence is None:
            match = HEADING_RE.match(line.rstrip("\n"))
            if match and "\0" not in line:
                headings.append((re.sub(r"[ \t]+#+$", "", match[2]), len(match[1]), offset, offset + len(original)))
        offset += len(original)
    matches = [i for i, heading in enumerate(headings) if heading[0] == locator["heading"]]
    if len(matches) != 1 or body[:headings[0][2]].strip():
        raise ValueError("missing/ambiguous section or unscoped document introduction")
    number = matches[0]
    ancestors = []
    for i, (_, depth, _, _) in enumerate(headings[:number]):
        while ancestors and headings[ancestors[-1]][1] >= depth:
            ancestors.pop()
        ancestors.append(i)
    while ancestors and headings[ancestors[-1]][1] >= headings[number][1]:
        ancestors.pop()
    for i in ancestors:
        title, _, _, content_start = headings[i]
        introduction = " ".join(body[content_start:headings[i + 1][2]].split())
        if title not in allowed_ancestors or not OPERATOR_CONTAINER_INTRO.fullmatch(introduction):
            raise ValueError("unsupported operator premise ancestor scope/context")
    _, depth, start, content_start = headings[number]
    end = next((position for _, level, position, _ in headings[number + 1:] if level <= depth), len(body))
    return " ".join(body[content_start:end].split())


def _operator_type_context(body: str, locator: dict, page: dict | None = None) -> tuple[str, list[str]]:
    """Input: verified source body/locator dict. Output: role str and all day constraints list. Accept finite complete contexts only."""
    if page is not None:
        _page_claim_context(page)
        if page['id'] != 'vector-datafields' or locator['heading'] != page['title']:
            raise ValueError('unsupported page type context; GROUP structural timing remains unsupported')
        core = [_documentation_text(block['value']) for block in page['content'] if block['type'] == 'TEXT']
        if not any(text in (' '.join(MATRIX_FACTS), MATRIX_PAGE_CONTEXT) for text in core):
            raise ValueError('missing explicit applicable MATRIX passages')
        if not any(locator['quote'] in text for text in core if text in (' '.join(MATRIX_FACTS), MATRIX_PAGE_CONTEXT)):
            raise ValueError('type premise must quote explicit MATRIX core, not summary/media')
        return 'matrix', []
    section = _operator_premise_section(body, locator, OPERATOR_TYPE_ANCESTORS)
    title = locator["heading"]
    for role, heading in OPERATOR_DOCUMENT_HEADINGS.items():
        medal = " \U0001f949" if role == "matrix" else " \U0001f948"
        if title not in (heading, heading + medal):
            continue
        explicit = " ".join(MATRIX_FACTS) if role == "matrix" else GROUP_FACT
        digest = hashlib.sha256(section.encode("utf-8")).hexdigest()
        if section != explicit and digest not in OPERATOR_TYPE_SECTION_HASHES[role]:
            raise ValueError("unsupported complete " + role + " context; unknown clauses or operator exceptions")
        return role, []
    constraints = INTEGER_WINDOW_PATTERN.findall(section)
    if (OPERATOR_WINDOW_HEADING.fullmatch(title) and constraints
            and not INTEGER_WINDOW_PATTERN.sub("", section).strip()):
        return "window", constraints
    raise ValueError("unsupported or unscoped complete operator type/parameter context")


def _operator_window_constraints(body: str) -> list[str]:
    """Input: complete verified Markdown str. Output: all applicable finite day constraints list or ValueError.

    A locator cannot hide a stricter rule in another section of the same source.
    Headings and operator/window mentions identify candidate contexts only;
    they never establish validity. Every candidate's complete contents must
    pass the finite grammar, including unquoted/unrecognized constraints.
    """
    headings = list(re.finditer(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*$", body, re.MULTILINE))
    constraints = []
    preamble = body[:headings[0].start()] if headings else body
    if OPERATOR_WINDOW_CANDIDATE.search(preamble):
        raise ValueError("unscoped window constraint context")
    for number, heading in enumerate(headings):
        title = re.sub(r"[ \t]+#+$", "", heading[1])
        end = headings[number + 1].start() if number + 1 < len(headings) else len(body)
        direct_contents = body[heading.end():end].strip()
        # Captured operator sections have their separate complete strict parser.
        if title.strip("`") == "ts_delta":
            continue
        if not (OPERATOR_WINDOW_HEADING.fullmatch(title) or
                direct_contents and (OPERATOR_WINDOW_CANDIDATE.search(title) and
                                     OPERATOR_WINDOW_SUBJECT.search(direct_contents)
                                     or OPERATOR_WINDOW_RELATION.search(direct_contents))):
            continue
        role, values = _operator_type_context(body, dict(heading=title))
        if role != "window":
            raise ValueError("window constraint outside applicable parameter context")
        constraints.extend(values)
    return constraints


def _capture_digest(value: object) -> str:
    """Input: finite JSON value. Output: SHA256 str. Match the raw Learn writer's UTF-8 payload identity."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _documentation_text(value: object) -> str:
    """Input: validated JSON block value. Output: str. Reproduce the capture writer's readable projection without dropping raw evidence."""
    if isinstance(value, str):
        semantic_html = re.sub(r'/\*.*?\*/', '', html.unescape(value), flags=re.DOTALL)
        if PAGE_SEMANTIC_HTML.search(semantic_html):
            raise ValueError('unsupported semantic HTML hidden/deleted/inert claim material')
        value = re.sub(r'<style.*?</style>', ' ', value, flags=re.IGNORECASE | re.DOTALL)
        return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', value)).split())
    if isinstance(value, list):
        return ' '.join(filter(None, (_documentation_text(item.get('value') or item.get('content') or item.get('text') or '')
            if isinstance(item, dict) else _documentation_text(item) for item in value)))
    if isinstance(value, dict):
        return ' '.join(_documentation_text(item) for item in value.values())
    return ''


def _documentation_blocks(content: object) -> None:
    """Input: page content object. Output: None. Validate finite lossless block schemas and unique IDs, never infer semantic trust."""
    if not isinstance(content, list) or not content:
        raise ValueError('documentation requires complete block list')
    seen = set()
    for block in content:
        if (not isinstance(block, dict) or set(block) != {'id', 'type', 'value'}
                or not isinstance(block['id'], str) or not block['id'].strip() or block['id'] in seen):
            raise ValueError('invalid/duplicate documentation block identity')
        seen.add(block['id'])
        kind, value = block['type'], block['value']
        if kind not in DOCUMENTATION_PAGE_POLICY['block_types']:
            raise ValueError('unknown documentation block type')
        valid = False
        if kind in ('TEXT', 'EQUATION'):
            valid = (isinstance(value, str) and bool(value.strip())
                     and not re.search(r'<!--|-->|<script\b', value, re.IGNORECASE))
        elif isinstance(value, dict):
            if kind == 'HEADING':
                valid = (set(value) == {'content', 'level'} and isinstance(value['content'], str)
                         and bool(value['content'].strip()) and value['level'] in ('1', '2', '3', '4', '5', '6'))
            elif kind == 'TABLE':
                data = value.get('data')
                valid = (set(value) == {'data', 'firstColIsHeader', 'firstRowIsTableHeader'}
                    and type(value['firstColIsHeader']) is bool and type(value['firstRowIsTableHeader']) is bool
                    and isinstance(data, list) and bool(data) and isinstance(data[0], list) and bool(data[0])
                    and all(isinstance(row, list) and len(row) == len(data[0])
                            and all(isinstance(cell, str) for cell in row) for row in data))
            elif kind == 'IMAGE':
                valid = (set(value) == {'fileSize', 'height', 'title', 'url', 'width'}
                    and all(type(value[key]) is int and value[key] > 0 for key in ('height', 'width'))
                    and type(value['fileSize']) is int and value['fileSize'] >= 0
                    and isinstance(value['title'], str) and bool(value['title'].strip())
                    and isinstance(value['url'], str) and re.fullmatch(r'https://[^\s/]+/\S+', value['url']) is not None)
            elif kind == 'SIMULATION_EXAMPLE':
                strings = {'instrumentType', 'language', 'maxTrade', 'nanHandling', 'neutralization',
                           'pasteurization', 'region', 'unitHandling', 'universe'}
                settings = value.get('settings')
                valid = (set(value) == {'regular', 'settings', 'type'} and value['type'] == 'REGULAR'
                    and isinstance(value['regular'], str) and bool(value['regular'].strip())
                    and isinstance(settings, dict) and set(settings) == strings | {'decay', 'delay', 'truncation'}
                    and all(isinstance(settings[key], str) and bool(settings[key].strip()) for key in strings)
                    and all(type(settings[key]) is int for key in ('decay', 'delay'))
                    and type(settings['truncation']) in (float, int))
        if not valid:
            raise ValueError('unsupported documentation block schema: ' + str(kind))


def _documentation_projection(content: list, rendered: str) -> bool:
    """Input: validated blocks and readable str. Output: bool. Match writer values losslessly modulo whitespace/dict order lost by sorted JSON."""
    target = ' '.join(rendered.split())

    def consume(value: object, position: int) -> set[int]:
        """Input: JSON value/int offset. Output: set[int]. Match exact visible scalar values in structural order."""
        if isinstance(value, str):
            text = _documentation_text(value)
            if not text:
                return {position}
            prefix = (' ' if position else '') + text
            return {position + len(prefix)} if target.startswith(prefix, position) else set()
        if isinstance(value, list):
            positions = {position}
            for item in value:
                positions = {end for start in positions for end in consume(item, start)}
            return positions
        if isinstance(value, dict):
            values = list(value.values())
            states = {(0, position)}
            for _ in values:
                states = {(mask | (1 << i), end) for mask, start in states
                          for i, item in enumerate(values) if not mask & (1 << i)
                          for end in consume(item, start)}
            return {end for _, end in states}
        return {position}

    return len(target) in consume([block['value'] for block in content], 0)


def _documentation_page(body: str, source: dict, raw: str | bytes) -> dict | None:
    """Input: verified body/index row/full raw text. Output: exact validated page dict or None for non-pages. No IO or new authority."""
    if not body.startswith('\n# Documentation Pages\n'):
        if 'Raw Documentation Payload' in body:
            raise ValueError('unsupported documentation container')
        return None
    match = re.fullmatch(r'(.*?)\n## Raw GET Receipt\n\n```json\n(.*)\n```\n', body, re.DOTALL)
    if not match or 'Raw GET Receipt' in match[1]:
        raise ValueError('documentation requires one complete GET receipt')
    receipt = json.loads(match[2], object_pairs_hook=_json_object, parse_constant=_invalid_constant)
    if not isinstance(receipt, dict) or set(receipt) != set(OPERATOR_RECEIPT_POLICY['keys']) or receipt['error'] is not None:
        raise ValueError('invalid documentation GET receipt')
    target, page = receipt['target'], receipt['payload']
    if (not isinstance(target, dict) or set(target) != {'kind', 'id'}
            or target['kind'] not in DOCUMENTATION_PAGE_POLICY['endpoints']
            or not isinstance(target['id'], str) or not isinstance(page, dict)
            or not set(DOCUMENTATION_PAGE_POLICY['page_keys']) <= page.keys()
            or not page.keys() <= set(DOCUMENTATION_PAGE_POLICY['page_keys'] + DOCUMENTATION_PAGE_POLICY['optional_page_keys'])
            or 'duration' in page and (not isinstance(page['duration'], str)
                or not re.fullmatch(DOCUMENTATION_PAGE_POLICY['duration_pattern'], page['duration']))):
        raise ValueError('unknown documentation target/page schema')
    page_id = target['id']
    if (page_id != page['id'] or page_id not in DOCUMENTATION_PAGE_POLICY['titles']
            or page['title'] not in DOCUMENTATION_PAGE_POLICY['titles'][page_id]
            or page['category'] != DOCUMENTATION_PAGE_POLICY['categories'][page_id]
            or (target['kind'] == 'operator_detail') != (page_id == 'ts_delta')
            or type(page['sequence']) is not int or page['sequence'] < 0):
        raise ValueError('documentation exact identity/title/category mismatch')
    if receipt['endpoint'] != DOCUMENTATION_PAGE_POLICY['endpoints'][target['kind']].replace('{id}', page_id):
        raise ValueError('documentation endpoint mismatch')
    _timestamp(page['lastModified'])
    _documentation_blocks(page['content'])
    text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    metadata, _ = parse_markdown_front_matter(text.replace('\r\n', '\n'))
    generated = receipt['generated_at']
    _timestamp(generated)
    expected = 'raw/platform/learn/' + generated.split('T')[0] + '/subset-' + _capture_digest(receipt) + '/documentation_pages.md'
    if (source['path'] != expected or metadata.get('source_path') != expected
            or generated != source['captured_at'] or generated != metadata.get('captured_at')
            or not metadata.keys() <= set(OPERATOR_RECEIPT_POLICY['header_keys']) | {'material_kind'}
            or any(not _equal(metadata.get(key), OPERATOR_RECEIPT_POLICY[key])
                   for key in ('capture_tool', 'content_status', 'update_check'))
            or not _equal(metadata.get('compiled_targets'), DOCUMENTATION_PAGE_POLICY['compiled_targets'])
            or type(metadata.get('record_count')) is not int or metadata['record_count'] != 1
            or metadata.get('payload_hash') != _capture_digest([page])
            or any(key in source and not _equal(source[key], metadata[key]) for key in ('record_count', 'payload_hash'))):
        raise ValueError('documentation capture path/date/hash/header mismatch')
    header = (f"\n# Documentation Pages\n\nRecord count: 1\n\n## {page['title']}\n\n"
              f"- Page id: `{page_id}`\n- Category: {page['category']}\n\n")
    prefix = match[1]
    if 'Raw Documentation Payload' in match[1]:
        duplicate = re.fullmatch(r'(.*?)\n## Raw Documentation Payload\n\n```json\n(.*)\n```\n', match[1], re.DOTALL)
        if (not duplicate or metadata.get('material_kind') != 'documentation_page'
                or not _equal(json.loads(duplicate[2], object_pairs_hook=_json_object, parse_constant=_invalid_constant), [page])):
            raise ValueError('documentation duplicate payload/render mismatch')
        prefix = duplicate[1]
    elif 'material_kind' in metadata:
        raise ValueError('documentation missing duplicate payload')
    if (not prefix.startswith(header) or not prefix.endswith('\n\n')
            or not _documentation_projection(page['content'], prefix[len(header):-2])):
        raise ValueError('documentation complete rendered payload mismatch')
    return page


def validated_documentation_page(ref: dict, source_index: dict, source_texts: dict) -> dict:
    """Input: evidence ref/index/full source dicts. Output: lossless page dict; raise ValueError if not a verified finite page. Pure, no trust flag."""
    body = _source(ref, source_index, source_texts)
    page = _documentation_page(body, source_index[ref['source_path']], source_texts[ref['source_path']])
    if page is None:
        raise ValueError('source is not a supported complete documentation page')
    return deepcopy(page)


def _page_constraint_text(value: object) -> str:
    """Input: block JSON value. Output: normalized inspection str. Preserve subscript boundaries, normalize Unicode, never rewrite source evidence."""
    if isinstance(value, str):
        value = PAGE_PARAMETER_SUBSCRIPT.sub(r'_\g<0>', html.unescape(value))
        value = unicodedata.normalize('NFKC', value)
        return re.sub(r'</?[A-Za-z][^<>]*>', ' ', value)
    if isinstance(value, list):
        return ' '.join(_page_constraint_text(item) for item in value)
    if isinstance(value, dict):
        return ' '.join(_page_constraint_text(item) for item in value.values())
    return ''


def _page_claim_context(page: dict) -> None:
    """Input: validated page dict. Output: None. Reject unreviewed relevant clauses anywhere, including summaries/media; retain unrelated prose."""
    page_id = page['id']
    explicit = {'ts_delta': [DELTA_PAGE_MEANING, DELTA_PAGE_INTRO, DELTA_PAGE_ILLUSTRATION],
                'vector-datafields': [' '.join(MATRIX_FACTS), MATRIX_PAGE_CONTEXT]}.get(page_id, [])
    for block in page['content']:
        text = _documentation_text(block['value'])
        normalized = ' '.join(text.split())
        if (page_id == 'simulation-settings' and normalized == REGULAR_DELAY_POLICY
                or page_id == 'fast-d1-documentation' and
                (re.fullmatch(NAMED_REGULAR_COMPARISON, normalized) or re.fullmatch(NAMED_CUTOFF_COMPARISON, normalized))):
            continue
        if block['type'] == 'HEADING':
            text = _documentation_text(block['value']['content'])
            if text in DOCUMENTATION_PAGE_POLICY['context_headings']:
                continue
        if text in explicit or _digest(text) in PAGE_ANCILLARY_DIGESTS.get(page_id, []):
            continue
        constraint_text = _page_constraint_text(block['value'])
        if page_id in DOCUMENTATION_PAGE_POLICY['parameter_guard_pages'] and PAGE_WINDOW_PARAMETER.search(constraint_text):
            raise ValueError('unsupported unrecognized window parameter clause in ' + page_id)
        if (PAGE_NUMERIC_RESTRICTION.search(constraint_text)
                or PAGE_WINDOW_PARAMETER.search(constraint_text) and PAGE_MATH_CONSTRAINT_MARKER.search(constraint_text)):
            raise ValueError('unsupported numeric documentation restriction in ' + page_id)
        if PAGE_RELEVANT_CLAUSE.search(text):
            raise ValueError('unsupported relevant documentation clause in ' + page_id)


def _page_target_timing(page: dict, field_id: str) -> None:
    """Input: validated FastD1 page/target field str. Output: None. Check every naming/cutoff pair involving the target, not just selected quotes."""
    expected = dict(regular=field_id, fast=field_id + REGULAR_DELAY_RULE['comparison_suffix'])
    for block in page['content']:
        text = ' '.join(_documentation_text(block['value']).split())
        for pattern in (NAMED_REGULAR_COMPARISON, NAMED_CUTOFF_COMPARISON):
            for match in re.finditer(pattern, text):
                facts = match.groupdict()
                if (field_id in facts.values() or expected['fast'] in facts.values()) and facts != expected:
                    raise ValueError('conflicting full-page target field naming/cutoff facts')


def page_rule_contract() -> dict:
    """Input: none. Output: JSON dict. Bind finite page grammar, scoped passages and context rules into receipts/job keys."""
    return dict(policy=deepcopy(DOCUMENTATION_PAGE_POLICY), meaning=DELTA_PAGE_MEANING,
                intro=DELTA_PAGE_INTRO, illustration=DELTA_PAGE_ILLUSTRATION,
                matrix_context=MATRIX_PAGE_CONTEXT, relevant_pattern=PAGE_RELEVANT_CLAUSE.pattern,
                numeric_pattern=PAGE_NUMERIC_RESTRICTION.pattern, semantic_html_pattern=PAGE_SEMANTIC_HTML.pattern,
                unknown_parameter_constraint_guard=dict(version=3, subject_pattern=PAGE_WINDOW_PARAMETER.pattern,
                    subject_flags=PAGE_WINDOW_PARAMETER.flags, normalization='NFKC', unicode_version=unicodedata.unidata_version,
                    subscript_pattern=PAGE_PARAMETER_SUBSCRIPT.pattern, subscript_flags=PAGE_PARAMETER_SUBSCRIPT.flags,
                    pages=DOCUMENTATION_PAGE_POLICY['parameter_guard_pages'],
                    legacy_marker_pattern=PAGE_MATH_CONSTRAINT_MARKER.pattern, legacy_marker_flags=PAGE_MATH_CONSTRAINT_MARKER.flags,
                    scope='reject_any_unrecognized_window_parameter_alias_after_finite_exemptions_without_notation_or_domain_evaluation'),
                timing_facts='all_target_and_counterpart_naming_and_cutoff_pairs_must_agree',
                ancillary_digests=deepcopy(PAGE_ANCILLARY_DIGESTS))


def _operator_receipt_context(body: str, source: dict, raw: str | bytes, operator: str, *, raw_capture: bool = False) -> str:
    """Input: verified complete body/index row/original text/operator. Output: interpretation body str or ValueError.

    Only the bounded capture writer's exact duplicate audit payload is non-new
    context. Validate all rows, the complete rendered body, header and subset
    identity before returning a view without the terminal receipt. Original
    text, source hashes and evidence locators are never changed. Tutorial and
    unknown receipt schemas remain explicitly unsupported, not ignored. The
    legacy raw_capture bool verifies exact rendering only, never V2 meanings.
    """
    if "Raw GET Receipt" not in body:
        return body
    match = re.fullmatch(r"(.*?)\n## Raw GET Receipt\n\n```json\n(.*)\n```\n", body, re.DOTALL)
    if not match or "Raw GET Receipt" in match[1]:
        raise ValueError("unsupported complete GET receipt container")
    receipt = json.loads(match[2], object_pairs_hook=_json_object, parse_constant=_invalid_constant)
    if not isinstance(receipt, dict) or set(receipt) != set(OPERATOR_RECEIPT_POLICY["keys"]) or receipt["error"] is not None:
        raise ValueError("unsupported GET receipt schema/error")
    target = receipt["target"]
    if not isinstance(target, dict) or target.get("kind") not in OPERATOR_RECEIPT_POLICY["endpoints"]:
        raise ValueError("unsupported GET receipt target")
    kind = target["kind"]
    if set(target) != ({"kind"} if kind == "operators" else {"kind", "id"}):
        raise ValueError("unsupported GET receipt target keys")
    if kind != "operators" and target["id"] != operator:
        raise ValueError("GET receipt target differs from selected operator")
    endpoint = OPERATOR_RECEIPT_POLICY["endpoints"][kind].replace("{id}", operator)
    if receipt["endpoint"] != endpoint:
        raise ValueError("GET receipt endpoint mismatch")
    payload = receipt["payload"]
    if kind == "operator_detail":
        rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and set(payload) <= set(OPERATOR_RECEIPT_POLICY["envelope_keys"]) and "results" in payload:
        rows = payload["results"]
        if (not isinstance(rows, list) or "count" in payload and
                (type(payload["count"]) is not int or payload["count"] < len(rows))
                or any(payload.get(key) is not None for key in ("next", "previous"))):
            raise ValueError("unsupported paginated operator receipt metadata")
    else:
        raise ValueError("unsupported operator receipt payload")
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing operator receipt rows")
    names = []
    for row in rows:
        if (not isinstance(row, dict) or not {"name", "scope", "definition", "description"} <= row.keys()
                or not row.keys() <= set(OPERATOR_RECEIPT_POLICY["row_keys"])):
            raise ValueError("unknown or missing operator receipt facts")
        name = row["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in names:
            raise ValueError("ambiguous operator receipt identity")
        names.append(name)
        if (not isinstance(row["scope"], list) or not row["scope"]
                or any(type(item) is not str or not re.fullmatch(r"[A-Z_]+", item) for item in row["scope"])
                or len(set(row["scope"])) != len(row["scope"])):
            raise ValueError("unsupported operator receipt scope")
        if raw_capture:
            continue
        for key in ("definition", "description"):
            value = row[key]
            if not isinstance(value, str) or not value or value != " ".join(value.split()) or any(c in value for c in "<>`"):
                raise ValueError("unsupported nonliteral operator receipt " + key)
        if (not isinstance(row.get("category", "Uncategorized"), str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z ]*", row.get("category") or "Uncategorized")
                or not isinstance(row.get("level", "unspecified"), str)
                or not re.fullmatch(r"[A-Za-z_]+", row.get("level", "unspecified"))
                or row.get("documentation", "") not in ("", "/operators/" + name)):
            raise ValueError("unsupported operator receipt nonconstraint metadata")
    if names.count(operator) != 1:
        raise ValueError("selected operator missing from receipt")
    selected = rows if kind == "operators" else [row for row in rows if row["name"] == operator]
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    metadata, _ = parse_markdown_front_matter(text.replace("\r\n", "\n"))
    generated_at = receipt["generated_at"]
    _timestamp(generated_at)
    expected_path = "raw/platform/learn/" + generated_at.split("T")[0] + "/subset-" + _capture_digest(receipt) + "/operators.md"
    if (source["path"] != expected_path or metadata.get("source_path") != expected_path
            or generated_at != source["captured_at"] or generated_at != metadata.get("captured_at")
            or not metadata.keys() <= set(OPERATOR_RECEIPT_POLICY["header_keys"])
            or any(not _equal(metadata.get(key), OPERATOR_RECEIPT_POLICY[key])
                   for key in ("capture_tool", "content_status", "update_check", "compiled_targets"))
            or type(metadata.get("record_count")) is not int or metadata["record_count"] != len(selected)
            or metadata.get("payload_hash") != _capture_digest(selected)
            or any(key in source and not _equal(source[key], metadata[key]) for key in ("record_count", "payload_hash"))):
        raise ValueError("GET receipt capture provenance/header mismatch")
    lines = ["", "# Operators", "", f"Record count: {len(selected)}", ""]
    categories = sorted({row.get("category") or "Uncategorized" for row in selected})
    for category in categories:
        lines.extend([f"## {category}", ""])
        for row in sorted((item for item in selected if (item.get("category") or "Uncategorized") == category),
                          key=lambda item: item["name"].lower()):
            lines.extend([f"### `{row['name']}`", "", f"- Source id: `{row['name']}`", f"- Scope: {row['scope']}",
                          f"- Level: {row.get('level', 'unspecified')}", f"- Documentation: {row.get('documentation', '')}",
                          f"- Definition: `{row['definition']}`", f"- Description: {row['description']}", ""])
    canonical = "\n".join(lines).rstrip() + "\n"
    if raw_capture:
        from wqb.knowledge_contracts import _learn_repair_body
        canonical = _learn_repair_body('operators', selected)
    if match[1] != canonical:
        raise ValueError("GET receipt does not reproduce complete captured operator cards")
    return canonical


def _direct_operator_definition(record: dict, source_index: dict, source_texts: dict) -> dict:
    """Input: record/index/full texts dicts. Output: typed definition dict or ValueError. Match explicit source types only."""
    from wqb.semantic_compilation import _markdown_definitions
    from wqb.knowledge_compile import _coverage_json_objects
    definition = operator_definition_from_dict(record["definition"])
    expected = {key: value for key, value in definition.items() if key != "evidence_refs"}
    for ref in definition["evidence_refs"]:
        body = _source(ref, source_index, source_texts)
        _documentation_page(body, source_index[ref['source_path']], source_texts[ref['source_path']])
        if _equal(_markdown_definitions(body).get(record["operator"]), expected):
            continue
        matches = [item.get("definition") for item in _coverage_json_objects(body)
                   if item.get("operator", item.get("name", item.get("id"))) == record["operator"]]
        if not matches or any(not isinstance(item, dict) or not _equal(
                {key: value for key, value in item.items() if key != "evidence_refs"}, expected) for item in matches):
            raise ValueError("direct typed definition absent or conflicting for this source operator")
    return definition


def resolve_operator_definition(record: dict, source_index: dict, source_texts: dict, *,
                                resource_contract_version: int = 1) -> dict:
    """Input: operator record/index/complete texts dicts, optional int version. Output: supported/unsupported result dict.

    V1 accepts directly documented types only. V2 additionally composes the
    three finite REGULAR Fast Expression rules. The signature proves syntax;
    separate scoped passages prove matrix input/result, GROUP input or integer
    days. Missing facts stay unsupported. No IO, publication or model authority.
    definition_digest is canonical SHA256 of the complete parsed definition,
    including documented refs. The returned receipt binds the rule and sources.
    """
    path = "definition"
    try:
        if type(resource_contract_version) is not int or resource_contract_version not in (1, 2):
            raise ValueError("unsupported resource contract version")
        if not isinstance(record, dict):
            raise ValueError("expected operator record object")
        definition = operator_definition_from_dict(record["definition"])
        basis = record.get("definition_basis")
        if resource_contract_version == 1 or basis is None:
            definition = _direct_operator_definition(record, source_index, source_texts)
            receipt = dict(kind="direct_documentation", operator=record["operator"], definition=definition,
                           definition_digest=_digest(definition))
            refs = definition["evidence_refs"]
        else:
            path = "definition_basis"
            basis = definition_basis_from_dict(basis)
            operator = record["operator"]
            rule = OPERATOR_RULES.get(operator)
            project_window = operator == "ts_delta" and basis["rule_id"] == "ts_delta_project_window"
            if project_window:
                rule = OPERATOR_RULES["ts_delta_project_window"]
            if rule is None or basis["operator"] != operator or any(
                    basis[key] != rule[key] for key in ("rule_id", "rule_version")):
                raise ValueError("unsupported operator rule/version/identity")
            if basis["definition_digest"] != _digest(definition):
                raise ValueError("definition digest mismatch")
            premises = [basis["signature_premise"], *basis["type_premises"]]
            if len({_digest(premise) for premise in premises}) != len(premises):
                raise ValueError("operator premises must be distinct")
            verified = []
            contexts = []
            for number, premise in enumerate(premises):
                path = f"definition_basis.premises[{number}]"
                value = verify_premise(premise, source_index, source_texts)
                ref, locator = premise["evidence_ref"], premise["locator"]
                if source_index[ref["source_path"]]["source_type"] != "platform_learn_material" or locator["kind"] != "markdown_quote":
                    raise ValueError("operator facts require applicable official Learn Markdown")
                if number:
                    body = _source(ref, source_index, source_texts)
                    page = _documentation_page(body, source_index[ref['source_path']], source_texts[ref['source_path']])
                    contexts.append(_operator_type_context(body, locator, page))
                verified.append((locator["heading"].strip("`"), " ".join(value.split()), premise))
            path = "definition_basis.signature_premise"
            signature = basis["signature_premise"]
            if signature["locator"]["heading"].strip("`") != operator:
                raise ValueError("signature heading does not identify exact operator")
            signature_ref = signature['evidence_ref']
            signature_body = _source(signature_ref, source_index, source_texts)
            page = _documentation_page(signature_body, source_index[signature_ref['source_path']], source_texts[signature_ref['source_path']])
            if page is not None:
                _page_claim_context(page)
                if operator != 'ts_delta' or page['id'] != operator or signature['locator']['quote'] != DELTA_PAGE_MEANING:
                    raise ValueError('page signature requires exact sourced operation prose')
                parameters = [dict(name=name, required=True) for name in rule['names']]
                description = DELTA_PAGE_MEANING
            else:
                parameters, description = _operator_signature(verify_premise(signature, source_index, source_texts), operator, rule)
                _operator_premise_section(signature_body, signature['locator'],
                                         {'Operators', 'Time Series' if operator == 'ts_delta' else 'Group'})
            if definition["description"] != description or description not in (
                    rule["meaning"], rule["meaning"] + OPERATOR_MEANING_SUFFIXES[operator],
                    *([DELTA_PAGE_MEANING] if operator == 'ts_delta' else [])):
                raise ValueError("definition meaning differs from sourced finite rule")
            # Inspect complete referenced captures as well as selected quotes;
            # a model cannot omit a contradictory labelled fact from its locator.
            from wqb.semantic_compilation import _markdown_definitions
            all_windows = []
            for source_path in {premise["evidence_ref"]["source_path"] for premise in premises}:
                ref = next(premise["evidence_ref"] for premise in premises if premise["evidence_ref"]["source_path"] == source_path)
                body = _source(ref, source_index, source_texts)
                page = _documentation_page(body, source_index[source_path], source_texts[source_path])
                if page is not None:
                    if page['id'] not in ('ts_delta', 'vector-datafields'):
                        raise ValueError('unsupported applicable operator page context')
                    _page_claim_context(page)
                    continue
                body = _operator_receipt_context(body, source_index[source_path], source_texts[source_path], operator)
                if operator == "ts_delta":
                    all_windows.extend(_operator_window_constraints(body))
                section = _operator_capture(body, operator)
                if section is None:
                    continue
                if not _equal(_operator_signature(section, operator, rule), (parameters, description)):
                    raise ValueError("conflicting captured operator signature/meaning")
                if re.search(r"^- (?:Input types|Output type|Parameters):", section, re.MULTILINE):
                    expected = {key: value for key, value in definition.items() if key != "evidence_refs"}
                    if not _equal(_markdown_definitions(body).get(operator), expected):
                        raise ValueError("conflicting or incomplete directly documented types")
            # These value-preserving operations produce one numeric value per
            # input instrument/date; generic Alpha shape alone is insufficient.
            path = "definition_basis.type_premises"
            matrix = [role for role, _ in contexts if role == "matrix"]
            group = [role for role, _ in contexts if role == "group"]
            window = [constraint for role, constraints in contexts if role == "window" for constraint in constraints]
            if operator == "ts_delta":
                window = sorted(set(window + all_windows))
            if not matrix:
                raise ValueError("missing applicable MATRIX input/output and vector-conversion facts")
            if operator == "ts_delta" and not window and not project_window:
                raise ValueError("missing applicable integer day-window constraint for ts_delta.d")
            if operator != "ts_delta" and not group:
                raise ValueError("missing explicit GROUP input applicability")
            for parameter, value_type in zip(parameters, rule["types"]):
                parameter["type"] = value_type
            if operator == "ts_delta" and "default" in parameters[1]:
                default = parameters[1]["default"]
                if type(default) is not int or any(default < (1 if "positive integer" in constraint else 0)
                                                   for constraint in window):
                    raise ValueError("window default conflicts with documented integer constraint")
                if project_window and not PROJECT_WINDOW_POLICY["minimum"] <= default <= PROJECT_WINDOW_POLICY["maximum"]:
                    raise ValueError("window default conflicts with project parameter policy")
            if not _equal(definition["parameters"], parameters) or any(not _equal(definition[key], rule[key])
                    for key in ("input_types", "output_type")):
                raise ValueError("typed interface conflicts with verified rule and signature")
            refs = [premise["evidence_ref"] for premise in premises]
            if {_digest(ref) for ref in definition["evidence_refs"]} != {
                    _digest(asdict(evidence_ref_from_dict(ref))) for ref in refs}:
                raise ValueError("definition evidence refs do not cover exact derivation sources")
            receipt = dict(kind="source_backed_derivation", operator=operator, definition=definition,
                           rule_id=rule["rule_id"], rule_version=rule["rule_version"],
                           rule_digest=_digest(dict(rule, matrix_facts=MATRIX_FACTS, group_fact=GROUP_FACT,
                               meaning_suffix=OPERATOR_MEANING_SUFFIXES[operator],
                               integer_pattern=INTEGER_WINDOW_PATTERN.pattern, headings=OPERATOR_DOCUMENT_HEADINGS,
                               context_policy_version=OPERATOR_CONTEXT_POLICY_VERSION,
                               receipt_policy=OPERATOR_RECEIPT_POLICY,
                               documentation_page_policy=DOCUMENTATION_PAGE_POLICY,
                               page_context=page_rule_contract(),
                               type_section_hashes={key: sorted(value) for key, value in OPERATOR_TYPE_SECTION_HASHES.items()},
                               type_ancestors=sorted(OPERATOR_TYPE_ANCESTORS), container_intro=OPERATOR_CONTAINER_INTRO.pattern,
                               window_heading=OPERATOR_WINDOW_HEADING.pattern,
                               window_candidate=OPERATOR_WINDOW_CANDIDATE.pattern,
                               window_subject=OPERATOR_WINDOW_SUBJECT.pattern, window_relation=OPERATOR_WINDOW_RELATION.pattern,
                               capture_line=OPERATOR_CAPTURE_LINE.pattern)),
                           definition_digest=_digest(definition), basis_digest=_digest(basis),
                           premise_digests=[_digest(premise) for premise in premises])
            if project_window:
                receipt["parameter_policy"] = deepcopy(PROJECT_WINDOW_POLICY)
                receipt["source_parameter_clauses"] = window
                receipt["rule_digest"] = _digest(dict(rule_digest=receipt["rule_digest"],
                                                      parameter_policy=PROJECT_WINDOW_POLICY))
            elif operator == "ts_delta":
                receipt["parameter_constraints"] = dict(d=dict(type="INTEGER", minimum=max(
                    1 if "positive integer" in constraint else 0 for constraint in window), clauses=window))
        sources = {}
        for ref in refs:
            source_path = ref["source_path"]
            source = source_index[source_path]
            raw = source_texts[source_path]
            raw = raw.encode("utf-8") if isinstance(raw, str) else raw
            sources[source_path] = dict(source_path=source_path, content_hash=source["content_hash"],
                                        file_sha256=hashlib.sha256(raw).hexdigest(), captured_at=source["captured_at"])
        receipt["sources"] = [sources[key] for key in sorted(sources)]
        receipt["receipt_digest"] = _digest(receipt)
        return dict(status="supported", value=receipt, rejections=[])
    except (ValueError, TypeError, KeyError, AttributeError, SyntaxError, OverflowError, RecursionError) as exc:
        return dict(status="unsupported", value=None,
                    rejections=[dict(code="unsupported_operator_definition", path=path, message=str(exc))])


def _check_timing_classification(quote: str, identity: dict, scope: dict) -> None:
    """Input: verified quote str, identity/scope dicts. Output: None or ValueError. Parse explicit scoped facts, not infer prose."""
    lines = [line.strip() for line in quote.splitlines() if line.strip()]
    if lines and lines[0].startswith("|"):
        if len(lines) != 3 or any(not line.startswith("|") or not line.endswith("|") for line in lines):
            raise ValueError("unsupported explicit classification table")
        cells = [[cell.strip() for cell in line[1:-1].split("|")] for line in lines]
        if cells[0] != TIMING_CLASSIFICATION_COLUMNS or any(len(row) != len(cells[0]) for row in cells):
            raise ValueError("unsupported timing classification columns")
        if any(not re.fullmatch(r":?-{3,}:?", cell) for cell in cells[1]):
            raise ValueError("unsupported timing classification separator")
        facts = dict(zip(cells[0], cells[2]))
    else:
        labels = {column.casefold(): column for column in TIMING_CLASSIFICATION_COLUMNS}
        labels.update({"dataset id": "Dataset", "field id": "Field"})
        facts = {}
        for statement in re.split(r"[;\n]", quote):
            if not statement.strip():
                continue
            pair = re.fullmatch(r"([A-Za-z_ ]+)\s*[:=]\s*(\S.*?)\s*", statement.strip())
            if not pair:
                raise ValueError("unsupported explicit classification statement")
            label = labels.get(pair[1].strip().replace("_", " ").casefold())
            if label is None or label in facts:
                raise ValueError("unknown or duplicate classification fact")
            facts[label] = pair[2]
        if set(facts) != set(TIMING_CLASSIFICATION_COLUMNS):
            raise ValueError("incomplete explicit classification identity/scope/cutoff/policy")
    cutoff = " ".join(facts["Cutoff class"].split()).casefold()
    policy = " ".join(facts["Timing policy"].split()).casefold()
    if cutoff not in REGULAR_DELAY_RULE["cutoff_labels"] or policy not in REGULAR_DELAY_RULE["policy_labels"]:
        raise ValueError("explicit classification does not establish regular timing and automatic delay")
    expected = [identity["dataset_id"], identity["field_id"], scope["instrument_type"], scope["region"],
                str(scope["delay"]), scope["universe"]]
    if [facts[key] for key in TIMING_CLASSIFICATION_COLUMNS[:6]] != expected:
        raise ValueError("documented classification identity/scope mismatch")


def _check_named_timing_comparison(premises: list[tuple], field_id: str) -> None:
    """Input: two verified (heading, quote, path) tuples and field ID str. Output: None or ValueError. Compose actual article facts."""
    if (len(premises) != 2 or len({path for _, _, path in premises}) != 1
            or any(heading != REGULAR_DELAY_RULE["comparison_heading"] for heading, _, _ in premises)):
        raise ValueError("named classification needs the naming and cutoff comparisons from the same official article")
    naming, timing = [], []
    for _, quote, _ in premises:
        normalized = " ".join(quote.split())
        name_match = re.fullmatch(NAMED_REGULAR_COMPARISON, normalized)
        cutoff_match = re.fullmatch(NAMED_CUTOFF_COMPARISON, normalized)
        if name_match:
            naming.append(name_match.groupdict())
        elif cutoff_match:
            timing.append(cutoff_match.groupdict())
        else:
            raise ValueError("unsupported named field/cutoff comparison passage")
    expected = dict(regular=field_id, fast=field_id + REGULAR_DELAY_RULE["comparison_suffix"])
    if naming != [expected] or timing != [expected]:
        raise ValueError("article does not explicitly classify this exact field and its cutoff as regular D1")


def resolve_timing_contract(contract: dict, field_row: dict, scope: dict,
                            source_index: dict, source_texts: dict) -> dict:
    """Input: contract/field/frozen scope/index/full texts dicts. Output: supported/unsupported result dict.

    Only regular_delay_1@3 is supported. Required premises: the actual settings
    Delay 1/automatic-delay passage and a complete /data-fields captured row
    (value_path=[]), plus either one explicitly scoped table/key-value record
    or two actual Fast D1 article passages: named regular/Fast D1 pair and
    named yesterday-close/today-open cutoff comparison. In the latter case,
    the article owns classification/cutoff; capture owns dataset identity and
    scope. Both comparisons must explicitly name this regular field and the
    same Fast D1 counterpart. Suffix absence never classifies other fields.
    Origin is derived from verified capture provenance and endpoint, never
    required as an invented API attribute. Missing classification or cutoff
    stays unsupported. All captured
    nested scope facts must agree with the locator's exact four-key scope.
    This certifies platform experiment timing only, never historical PIT.
    No IO, model calls, current-clock defaults or synthetic availability.
    """
    path = "timing_contract"
    try:
        parsed = timing_contract_from_dict(contract)
        if not isinstance(scope, dict) or not isinstance(field_row, dict):
            raise ValueError("expected field row and frozen scope objects")
        keys = REGULAR_DELAY_RULE["source_scope_keys"]
        requested = resource_scope_from_dict({key: scope[key] for key in keys})
        if not _equal(parsed["scope"], requested) or requested["delay"] != 1:
            raise ValueError("policy requires exact captured regular Delay 1 scope")
        if any(parsed[key] != REGULAR_DELAY_RULE[key] for key in ("rule_id", "rule_version", "cutoff_class")):
            raise ValueError("unsupported timing rule/version/cutoff class")
        identity = dict(dataset_id=field_row.get("dataset_id"), field_id=field_row.get("field_id", field_row.get("id")))
        if not _equal(identity, parsed["field_identity"]):
            raise ValueError("policy field identity mismatch")
        if "id" in field_row and not _equal(field_row["id"], identity["field_id"]):
            raise ValueError("conflicting field identity alias")
        if "dataset_id" in scope and not _equal(scope["dataset_id"], identity["dataset_id"]):
            raise ValueError("requested dataset identity mismatch")
        _check_scoped_facts({key: value for key, value in field_row.items()
                             if key not in ("available_scopes", "timing_contract")}, requested)
        captured_scopes = field_row.get("available_scopes", [field_row])
        if not isinstance(captured_scopes, list):
            raise ValueError("field snapshot requires captured scope tuples")
        matching_scopes = [item for item in captured_scopes if isinstance(item, dict)
                           and all(key in item and _equal(item[key], requested[key]) for key in keys)]
        if not matching_scopes:
            raise ValueError("field snapshot does not contain the exact captured scope tuple")
        for item in matching_scopes:
            _check_scoped_facts({key: value for key, value in item.items()
                                 if key not in ("available_scopes", "timing_contract")}, requested)
        as_of = _timestamp(scope.get("as_of"))
        if "available_at" in field_row and _timestamp(field_row["available_at"]) > as_of:
            raise ValueError("explicit available_at is in the future")
        if len(parsed["premises"]) not in (3, 4) or len({_digest(p) for p in parsed["premises"]}) != len(parsed["premises"]):
            raise ValueError("policy needs distinct policy, applicability and captured field premises")
        docs, captured_rows, sources = [], [], {}
        for i, premise in enumerate(parsed["premises"]):
            path = f"timing_contract.premises[{i}]"
            value = verify_premise(premise, source_index, source_texts)
            ref, locator = premise["evidence_ref"], premise["locator"]
            source = source_index[ref["source_path"]]
            captured_at = _timestamp(source["captured_at"])
            if not timedelta(0) <= as_of - captured_at <= timedelta(days=KNOWLEDGE_MAX_AGE_DAYS):
                raise ValueError("source capture is future or exceeds knowledge age policy")
            supplied = source_texts[ref["source_path"]]
            raw = supplied.encode("utf-8") if isinstance(supplied, str) else supplied
            sources[ref["source_path"]] = dict(source_path=ref["source_path"], content_hash=source["content_hash"],
                                               file_sha256=hashlib.sha256(raw).hexdigest(), captured_at=source["captured_at"])
            if source["source_type"] == "platform_learn_material" and locator["kind"] == "markdown_quote":
                page = _documentation_page(_source(ref, source_index, source_texts), source, supplied)
                if page is not None:
                    if page['id'] not in ('simulation-settings', 'fast-d1-documentation') or locator['heading'] != page['title']:
                        raise ValueError('unsupported timing page applicability')
                    _page_claim_context(page)
                    if page['id'] == 'fast-d1-documentation':
                        _page_target_timing(page, identity['field_id'])
                docs.append((locator["heading"], value, ref["source_path"]))
            elif (source["source_type"] == "platform_data_field_capture" and locator["kind"] == "json_value"
                  and locator["value_path"] == REGULAR_DELAY_RULE["capture_value_path"]
                  and _equal(locator["row_identity"], dict(identity, scope=requested))):
                if not isinstance(value, dict) or value.get("endpoint") != REGULAR_DELAY_RULE["capture_endpoint"]:
                    raise ValueError("origin requires verified official /data-fields capture endpoint")
                captured_rows.append((ref["source_path"], value))
            else:
                raise ValueError("unsupported timing premise role/source family/value path")
        path = "timing_contract.premises"
        policies = [value for heading, value, _ in docs if heading == REGULAR_DELAY_RULE["policy_heading"]
                    and REGULAR_DELAY_POLICY in " ".join(value.split())]
        classifications = [(heading, value, path) for heading, value, path in docs if not (
            heading == REGULAR_DELAY_RULE["policy_heading"] and REGULAR_DELAY_POLICY in " ".join(value.split()))]
        if len(policies) != 1 or len(classifications) not in (1, 2) or len(captured_rows) != 1:
            raise ValueError("missing actual automatic-delay policy or separate documented classification")
        if len(classifications) == 1:
            _check_timing_classification(classifications[0][1], identity, requested)
        else:
            _check_named_timing_comparison(classifications, identity["field_id"])
        capture_path, capture = captured_rows[0]
        field = capture.get("field")
        if not isinstance(field, dict):
            raise ValueError("missing captured field object")
        if (not _equal(field.get("id"), identity["field_id"]) or not isinstance(field.get("dataset"), dict)
                or not _equal(field["dataset"].get("id"), identity["dataset_id"])):
            raise ValueError("captured field identity mismatch")
        if field.get("type") not in REGULAR_DELAY_RULE["field_types"] or not _equal(
            field.get("type"), field_row.get("field_type", field_row.get("type"))
        ):
            raise ValueError("captured field type unsupported or mismatched; no VECTOR timing support")
        for facts in (capture, field, field_row):
            for key, expected in (("origin", "platform"), ("cutoff_class", "regular_delay_1")):
                if key in facts and not _equal(facts[key], expected):
                    raise ValueError("explicit fact contradicts derived " + key)
        if "type" in field_row and not _equal(field_row["type"], field["type"]):
            raise ValueError("field snapshot contradicts captured type")
        if "available_at" in field:
            captured_available = _timestamp(field["available_at"])
            if captured_available > as_of:
                raise ValueError("captured available_at is in the future")
            if "available_at" in field_row and captured_available != _timestamp(field_row["available_at"]):
                raise ValueError("explicit available_at contradicts captured availability")
        receipt = {key: deepcopy(parsed[key]) for key in ("kind", "scope", "cutoff_class", "field_identity", "rule_id", "rule_version", "historical_pit_verified")}
        receipt.update(contract_digest=_digest(parsed), policy_digest=_digest(sorted(docs)),
                       rule_digest=_digest(dict(rule=REGULAR_DELAY_RULE, page_context=page_rule_contract())), validated_as_of=scope["as_of"],
                       origin_basis=dict(source_path=capture_path, endpoint=capture["endpoint"], derived_origin="platform"),
                       sources=[sources[key] for key in sorted(sources)])
        receipt["receipt_digest"] = _digest(receipt)
        return dict(status="supported", value=receipt, rejections=[])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        return dict(status="unsupported", value=None,
                    rejections=[dict(code="unsupported_timing_contract", path=path, message=str(exc))])
