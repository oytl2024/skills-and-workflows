"""Pure BRAIN/Python AST spelling bridge; parsing never executes an expression."""
import ast
import io
import tokenize


LOGICAL_CALLS = frozenset({'and', 'or', 'not'})
OPERATOR_PREFIX = '__brain_logical_'
BOOLEAN_INPUTS = {'true': 'True', 'false': 'False'}
BOOLEAN_OUTPUTS = {'True': 'true', 'False': 'false'}


def protect_literal_braces(text: str) -> str:
    """Input: template str. Output: str escaping only quoted braces before placeholder formatting,not actual field slots."""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        return tokenize.untokenize([
            token._replace(string=token.string.replace('{', '{{').replace('}', '}}'))
            if token.type == tokenize.STRING else token for token in tokens])
    except (tokenize.TokenError, IndentationError) as error:
        raise ValueError('Invalid local expression tokens') from error


def parse_expression(text: str) -> ast.expr:
    """Input: BRAIN expression str. Output: Python AST with original call names; no evaluation or signature inference."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError) as error:
        raise ValueError('Invalid local expression tokens') from error
    rewritten = []
    for index, token in enumerate(tokens):
        value = token.string
        if token.type == tokenize.NAME:
            if value.startswith(OPERATOR_PREFIX):
                raise ValueError('Reserved local syntax identifier')
            following = next((other.string for other in tokens[index+1:]
                              if other.type not in (tokenize.NL, tokenize.COMMENT)), '')
            if value in LOGICAL_CALLS and following == '(':
                value = OPERATOR_PREFIX + value
            else:
                value = BOOLEAN_INPUTS.get(value, value)
        rewritten.append(token._replace(string=value))
    node = ast.parse(tokenize.untokenize(rewritten), mode='eval').body
    for item in ast.walk(node):
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
            if item.func.id.startswith(OPERATOR_PREFIX):
                item.func.id = item.func.id[len(OPERATOR_PREFIX):]
    return node


def render_expression(node: ast.expr) -> str:
    """Input: supported AST. Output: BRAIN expression str with lowercase booleans and unchanged string literals."""
    text = ast.unparse(ast.fix_missing_locations(node))
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return tokenize.untokenize([
        token._replace(string=BOOLEAN_OUTPUTS.get(token.string, token.string))
        if token.type == tokenize.NAME else token for token in tokens])
