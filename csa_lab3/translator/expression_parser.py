import ast
import random
import re
from _ast import *  # noqa: F403


class ExpressionTreeVisitor(ast.NodeVisitor):
    _allowed_nodes = (Expression, Name, Constant, Add, Sub, Mult, Div, Mod, And, Or, Not, Eq, NotEq, Lt, LtE, Gt, GtE, UAdd, USub)

    def __init__(self, var_temp_postfix: str):
        self.tokens = []
        self._var_temp_postfix_len = len(var_temp_postfix)

    def generic_visit(self, node):
        assert isinstance(node, self._allowed_nodes), 'Invalid operation in expression'
        assert type(node) is not Constant or type(node.value) in (int, str), 'Only int or str types are allowed'
        self.tokens.append(node)
        super().generic_visit(node)

    def visit_BinOp(self, node):  # noqa: N802
        self.visit(node.right)
        self.visit(node.left)
        self.visit(node.op)

    def visit_BoolOp(self, node):  # noqa: N802
        for value in node.values:
            self.visit(value)
        self.visit(node.op)

    def visit_Compare(self, node):  # noqa: N802
        assert len(node.ops) == 1, 'Multiple comparisons are not allowed'
        self.visit(node.comparators[0])
        self.visit(node.left)
        self.visit(node.ops[0])

    def visit_UnaryOp(self, node):  # noqa: N802
        self.visit(node.operand)
        self.visit(node.op)

    def visit_Name(self, node):  # noqa: N802
        node.id = node.id[: -self._var_temp_postfix_len]  # remove temp postfix
        self.tokens.append(node)


class ExpressionParser:
    _var_temp_postfix: str = f'_{random.getrandbits(32):x}'

    def __init__(self, expression: str):
        self.expression = expression

    def _to_python_expression(self) -> str:
        # add temp postfix to variable names so ast parser doesn't confuse variables with python keywords
        expression = re.sub(r'(?<!\w|\')([a-zA-Z_]\w*)', rf'\1{self._var_temp_postfix}', self.expression)
        # replace `!` with `not` TODO: add the replacement for `!` before nested parentheses
        expression = re.sub(r'!(\w+|\([^()]+\))', r'(not \1)', expression)
        # replace `||` and `&&` with `or` and `and`
        return expression.replace('||', ' or ').replace('&&', ' and ')

    def parse(self) -> list:
        expression = self._to_python_expression()
        ast_tree = ast.parse(expression, mode='eval')
        tree_visitor = ExpressionTreeVisitor(self._var_temp_postfix)
        tree_visitor.visit(ast_tree)
        return tree_visitor.tokens[1:]  # skip Expression node
