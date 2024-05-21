import re
import sys
from _ast import *  # noqa: F403
from typing import Literal, NamedTuple

from machine.isa import AddressingMode, Instruction, Opcode, machine2binary

from .expression_parser import ExpressionParser


class Variable(NamedTuple):
    type: type[int | str]
    addr: int


class Block(NamedTuple):
    type: Literal['while', 'if']
    jump_addr: int
    start_addr: int = None  # for loops only


class Translator:
    KEYWORDS = ('var', 'if', 'while')
    STR_MAX_LENGTH = 63

    def __init__(self):
        self.instructions: list[Instruction] = []
        self.string_literal_mem: list[int] = []  # string literals zone in memory: size1, chars1[], size2, chars2[]...
        self.string_literal_pointers: dict[str, int] = {}  # string literal: addr
        self.mem_pointer: int = 0  # points to the cell in variables zone after the last declared variable
        self.variables: dict[str, Variable] = {}  # name: Variable(type, addr)
        self.blocks: list[Block] = []
        self.block_variables: list[list[str]] = [[]]

    def _save_variable(self, name: str, var_type: type[str | int], value_addr: int) -> int:
        var = self.variables.get(name)
        if var is None:
            var = self.variables[name] = Variable(var_type, self.mem_pointer)
            self.mem_pointer += 1
            if var_type is str:
                self.mem_pointer += self.STR_MAX_LENGTH
            self.block_variables[-1].append(name)
        if var_type is int:
            self.instructions.append(Instruction(Opcode.LD, value_addr))
            self.instructions.append(Instruction(Opcode.ST, var.addr))
        else:
            self._copy_string(src_addr=value_addr, dest_addr=var.addr)
        return var.addr

    def _copy_string(self, src_addr: int, dest_addr: int):
        self.instructions.append(Instruction(Opcode.LD, 0, AddressingMode.IMMEDIATE))  # p = 0
        self.instructions.append(Instruction(Opcode.ST, dest_addr))  # s1_length = p

        self.instructions.append(Instruction(Opcode.CMP, src_addr))  # while p != s0_length:
        self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 14))
        self.instructions.append(Instruction(Opcode.ADD, 1, AddressingMode.IMMEDIATE))  # p += 1
        self.instructions.append(Instruction(Opcode.ST, dest_addr))  # s1_length = p
        self.instructions.append(Instruction(Opcode.ADD, src_addr, AddressingMode.IMMEDIATE))  # i = p + s0_addr
        self.instructions.append(Instruction(Opcode.ST, self.mem_pointer))
        self.instructions.append(Instruction(Opcode.LD, self.mem_pointer, AddressingMode.INDIRECT))  # char = s0[i]
        self.instructions.append(Instruction(Opcode.ST, self.mem_pointer))
        self.instructions.append(Instruction(Opcode.LD, dest_addr, AddressingMode.IMMEDIATE))  # j = s1_addr
        self.instructions.append(Instruction(Opcode.ADD, dest_addr))  # j += s1_length
        self.instructions.append(Instruction(Opcode.ST, self.mem_pointer + 1))
        self.instructions.append(Instruction(Opcode.LD, self.mem_pointer))  # s1[j] = char
        self.instructions.append(Instruction(Opcode.ST, self.mem_pointer + 1, AddressingMode.INDIRECT))

        self.instructions.append(Instruction(Opcode.LD, dest_addr))  # p = s1_length
        self.instructions.append(Instruction(Opcode.JMP, len(self.instructions) - 14))

    def _handle_expression(self, expression: str) -> int:  # noqa: C901
        stack_pointer = self.mem_pointer
        for node in ExpressionParser(expression).parse():
            node_type = type(node)
            if node_type is Name:
                var = self.variables.get(node.id)
                assert var, f'Cannot find variable {node.id}'
                self.instructions.append(Instruction(Opcode.LD, var.addr))
                self.instructions.append(Instruction(Opcode.ST, stack_pointer))
                stack_pointer += 1
            elif node_type is Constant:
                constant_value = node.value
                if type(constant_value) is str:
                    constant_value = len(constant_value)
                else:
                    assert -(2**31) <= constant_value <= 2**31 - 1, 'Numbers must be between -2^31 and 2^31-1'
                self.instructions.append(Instruction(Opcode.LD, constant_value, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.ST, stack_pointer))
                stack_pointer += 1
            elif node_type is UAdd:
                pass
            elif node_type is USub:
                self.instructions.append(Instruction(Opcode.MUL, -1, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.ST, stack_pointer - 1))
            elif node_type is Not:
                self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 3))
                self.instructions.append(Instruction(Opcode.LD, 0, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.JMP, len(self.instructions) + 2))
                self.instructions.append(Instruction(Opcode.LD, 1, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.ST, stack_pointer - 1))
            elif node_type is Or:
                self.instructions.append(Instruction(Opcode.JNE, len(self.instructions) + 5))
                self.instructions.append(Instruction(Opcode.LD, stack_pointer - 2))
                self.instructions.append(Instruction(Opcode.JNE, len(self.instructions) + 3))
                self.instructions.append(Instruction(Opcode.LD, 0, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.JMP, len(self.instructions) + 2))
                self.instructions.append(Instruction(Opcode.LD, 1, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.ST, stack_pointer - 2))
                stack_pointer -= 1
            elif node_type is And:
                self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 5))
                self.instructions.append(Instruction(Opcode.LD, stack_pointer - 2))
                self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 3))
                self.instructions.append(Instruction(Opcode.LD, 1, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.JMP, len(self.instructions) + 2))
                self.instructions.append(Instruction(Opcode.LD, 0, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.ST, stack_pointer - 2))
                stack_pointer -= 1
            elif node_type in (Add, Sub, Mult, Div, Mod, And, Or):
                self.instructions.append(Instruction({Add: Opcode.ADD,
                                                      Sub: Opcode.SUB,
                                                      Mult: Opcode.MUL,
                                                      Div: Opcode.DIV,
                                                      Mod: Opcode.MOD}[node_type],
                                         stack_pointer - 2))  # fmt: skip
                self.instructions.append(Instruction(Opcode.ST, stack_pointer - 2))
                stack_pointer -= 1
            elif node_type in (Eq, NotEq, Lt, LtE, Gt, GtE):
                self.instructions.append(Instruction(Opcode.CMP, stack_pointer - 2))
                if node_type in (Lt, LtE):
                    self.instructions.append(Instruction(Opcode.JL, len(self.instructions) + 3 + (node_type is LtE)))
                elif node_type in (Gt, GtE):
                    self.instructions.append(Instruction(Opcode.JG, len(self.instructions) + 3 + (node_type is GtE)))
                if node_type in (Eq, LtE, GtE):
                    self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 3))
                elif node_type is NotEq:
                    self.instructions.append(Instruction(Opcode.JNE, len(self.instructions) + 3))
                self.instructions.append(Instruction(Opcode.LD, 0, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.JMP, len(self.instructions) + 2))
                self.instructions.append(Instruction(Opcode.LD, 1, AddressingMode.IMMEDIATE))
                self.instructions.append(Instruction(Opcode.ST, stack_pointer - 2))
                stack_pointer -= 1

        return self.mem_pointer

    def process_variable_assignment(self, statement: str) -> bool:
        if (parsed := re.match(r'([_a-zA-Z]\w*) *= *(.+)', statement)) is None:  # (?:var +)?
            return False

        var_name, expression = parsed.groups()
        assert var_name not in self.KEYWORDS, f'{var_name} cannot be used as a variable name'

        if re.match(r"'([^']*)'$", expression):  # string literal
            string_literal_addr = self.string_literal_pointers[expression[1:-1]]
            self._save_variable(var_name, str, string_literal_addr)
        elif re.match(r'[_a-zA-Z]\w*$', expression):  # single variable
            value_var = self.variables.get(expression)
            assert value_var, f'Cannot find variable {expression}'
            self._save_variable(var_name, value_var.type, value_var.addr)
        else:  # expression
            value_addr = self._handle_expression(expression)
            self._save_variable(var_name, int, value_addr)

        return True

    def process_if_statement(self, statement: str) -> bool:  # TODO add ELSE
        if (parsed := re.match(r'if +(.+) *:$', statement)) is None:
            return False

        expression = parsed.group(1)
        self._handle_expression(expression)
        self.instructions.append(Instruction(Opcode.CMP, 0, AddressingMode.IMMEDIATE))
        self.instructions.append(Instruction(Opcode.JE))  # jump address will be set later, after `;`
        self.blocks.append(Block('if', len(self.instructions) - 1))
        self.block_variables.append([])

        return True

    def process_while_statement(self, statement: str) -> bool:
        if (parsed := re.match(r'while +(.+) *:$', statement)) is None:
            return False

        expression = parsed.group(1)

        block_start_addr = len(self.instructions)
        self._handle_expression(expression)
        self.instructions.append(Instruction(Opcode.CMP, 0, AddressingMode.IMMEDIATE))
        self.instructions.append(Instruction(Opcode.JE))  # jump address will be set later, after `;`
        self.blocks.append(Block('while', len(self.instructions) - 1, block_start_addr))
        self.block_variables.append([])

        return True

    def process_block_closure(self, statement: str) -> bool:
        if statement != ';':
            return False
        assert len(self.blocks) > 0, 'Unexpected ;'

        block = self.blocks.pop()
        if block.type == 'while':
            self.instructions.append(Instruction(Opcode.JMP, block.start_addr))
        self.instructions[block.jump_addr] = self.instructions[block.jump_addr]._replace(argument=len(self.instructions))

        # clear the block, deleting all the variables declared in it
        for block_var in self.block_variables.pop():
            self.variables.pop(block_var)

        return True

    def process_input_command(self, statement: str) -> bool:
        if (parsed := re.match(r'/in +([_a-zA-Z]\w*)', statement)) is None:
            return False

        var_name = parsed.group(1)
        var = self.variables.get(var_name)
        assert var, f'Cannot find variable {var_name}'
        assert var.type is str, f'Cannot input variable {var_name}, must have str type'

        self.instructions.append(Instruction(Opcode.LD, 0, AddressingMode.IMMEDIATE))
        self.instructions.append(Instruction(Opcode.ST, var.addr))

        self.instructions.append(Instruction(Opcode.IN))
        self.instructions.append(Instruction(Opcode.CMP, 0, AddressingMode.IMMEDIATE))
        self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 13))
        self.instructions.append(Instruction(Opcode.ST, self.mem_pointer))
        self.instructions.append(Instruction(Opcode.LD, var.addr))
        self.instructions.append(Instruction(Opcode.ADD, 1, AddressingMode.IMMEDIATE))
        self.instructions.append(Instruction(Opcode.ST, var.addr))
        self.instructions.append(Instruction(Opcode.ADD, var.addr, AddressingMode.IMMEDIATE))
        self.instructions.append(Instruction(Opcode.ST, self.mem_pointer + 1))
        self.instructions.append(Instruction(Opcode.LD, self.mem_pointer))
        self.instructions.append(Instruction(Opcode.ST, self.mem_pointer + 1, AddressingMode.INDIRECT))
        self.instructions.append(Instruction(Opcode.LD, var.addr))
        self.instructions.append(Instruction(Opcode.CMP, self.STR_MAX_LENGTH, AddressingMode.IMMEDIATE))
        self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 2))
        self.instructions.append(Instruction(Opcode.JMP, len(self.instructions) - 14))

        return True

    def process_output_command(self, statement: str) -> bool:
        if (parsed := re.match(r'(?:/out |>) *(.+)', statement)) is None:
            return False

        expression = parsed.group(1)
        if re.match(r"'([^']*)'$", expression):  # string literal
            data_addr = self.string_literal_pointers[expression[1:-1]]
            data_type = str
        elif re.match(r'[_a-zA-Z]\w*$', expression):  # single variable
            var = self.variables.get(expression)
            assert var, f'Cannot find variable {expression}'
            data_addr = var.addr
            data_type = var.type
        else:  # expression
            data_addr = self._handle_expression(expression)
            data_type = int

        if data_type is int:
            self.instructions.append(Instruction(Opcode.LD, data_addr))
            self.instructions.append(Instruction(Opcode.OUTN))
        else:
            self.instructions.append(Instruction(Opcode.LD, 0, AddressingMode.IMMEDIATE))  # p = 0
            self.instructions.append(Instruction(Opcode.ST, self.mem_pointer))
            self.instructions.append(Instruction(Opcode.CMP, data_addr))  # while p != s_length:
            self.instructions.append(Instruction(Opcode.JE, len(self.instructions) + 9))
            self.instructions.append(Instruction(Opcode.ADD, 1, AddressingMode.IMMEDIATE))  # p += 1
            self.instructions.append(Instruction(Opcode.ST, self.mem_pointer))
            self.instructions.append(Instruction(Opcode.ADD, data_addr, AddressingMode.IMMEDIATE))  # i = p + s_addr
            self.instructions.append(Instruction(Opcode.ST, self.mem_pointer + 1))
            self.instructions.append(Instruction(Opcode.LD, self.mem_pointer + 1, AddressingMode.INDIRECT))  # /out s[i]
            self.instructions.append(Instruction(Opcode.OUT))
            self.instructions.append(Instruction(Opcode.LD, self.mem_pointer))
            self.instructions.append(Instruction(Opcode.JMP, len(self.instructions) - 9))

        return True

    def translate(self, code: str):
        code = code.strip().replace('\t', ' ' * 4).replace('\n\n', '\n')

        # store string literals
        for string in re.findall(r"'([^'\n]*)'", code):
            assert (
                len(string) <= self.STR_MAX_LENGTH
            ), f'The length of `{string}` string is greater than {self.STR_MAX_LENGTH} characters'
            self.string_literal_pointers[string] = len(self.string_literal_mem)
            self.string_literal_mem += [len(string)] + [ord(char) for char in string]
        self.mem_pointer = len(self.string_literal_mem)

        # translate code
        for line in code.split('\n'):
            statement = line.strip()
            if not statement:
                continue
            statement_executed = (
                self.process_variable_assignment(statement)
                or self.process_if_statement(statement)
                or self.process_while_statement(statement)
                or self.process_block_closure(statement)
                or self.process_output_command(statement)
                or self.process_input_command(statement)
            )
            assert statement_executed, 'Invalid code: ' + statement
        assert self.blocks == [], 'Unclosed blocks'
        self.instructions.append(Instruction(Opcode.HLT))


def code2machine(code: str) -> tuple[list[Instruction], list[int]]:
    translator = Translator()
    translator.translate(code)
    return translator.instructions, translator.string_literal_mem


def main(source_file: str, target_file: str, target_debug_file: str):
    with open(source_file, encoding='utf-8') as f:
        source_code = f.read()
    instructions, memory = code2machine(source_code)

    binary = machine2binary(instructions, memory)
    with open(target_file, 'wb') as f:
        f.write(binary)

    with open(target_debug_file, 'w', encoding='utf-8') as f:
        f.write('~~~~~ INSTRUCTIONS ~~~~~')
        f.write(f'\n{"address":<10}{"hexcode":<15}mnemonic')
        for i, instr in enumerate(instructions):
            f.write(f'\n{i:<10}{binary[i * 5 : i * 5 + 5].hex():<15}{instr}')
        f.write('\n~~~~~ MEMORY ~~~~~')
        f.write(f'\n{"address":<10}int')
        for i, value in enumerate(memory):
            f.write(f'\n{i:<10}{value}')

    print('source LoC:', source_code.count('\n') + 1)
    print('code instr:', len(instructions))
    print('code bytes:', len(instructions) * 5)  # machine instr word consist of 5 bytes


if __name__ == '__main__':
    assert len(sys.argv) == 4, 'Wrong arguments: translator.py <source_file> <target_file> <target_debug_file>'
    _, source_file, target_file, target_debug_file = sys.argv
    main(source_file, target_file, target_debug_file)
